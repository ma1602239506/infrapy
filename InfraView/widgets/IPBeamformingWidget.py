from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
                             QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox,
                             QGroupBox, QComboBox, QSplitter, QTabWidget, QAction,
                             QToolBar, QToolButton)

from PyQt5.QtCore import pyqtSignal, pyqtSlot, Qt, QThread, QCoreApplication, QLine
from PyQt5 import QtCore, QtGui
from PyQt5.QtGui import QFont, QFontDatabase, QIcon

import pyqtgraph as pg
from pyqtgraph import ViewBox

import platform
import numpy as np
from scipy import signal
from operator import itemgetter

# import infraview widgets here
from InfraView.widgets import IPDetectionWidget
from InfraView.widgets import IPPickLine
from InfraView.widgets import IPPickItem
from InfraView.widgets import IPPlotWidget
from InfraView.widgets import IPBeamformingSettingsWidget
from InfraView.widgets import IPPolarPlot
from InfraView.widgets import IPLine

# import infrapy modules here
from infrapy.detection import beamforming_new

# import obspy modules here
from obspy.core import UTCDateTime, read

# multiprocessing modules
import pathos.multiprocessing as mp
from multiprocessing import cpu_count


class IPBeamformingWidget(QWidget):

    signal_startBeamforming = pyqtSignal()
    signal_stopBeamforming = pyqtSignal()

    _streams = None

    _hlines = []  # list to hold the horizontal crosshair lines
    _vlines = []  # list to hold the vertical crosshair lines
    _position_labels = []  # list to hold the labels that show the position of the crosshairs
    _value_labels = []  # list to hold the labels that show the y-value of the crosshairs

    _plot_list = []     # list to hold references to the four main plots

    _slowness_collection = []   # This will hold the slowness plots for the current run
    _max_projection_data = None

    _t = []
    _trace_vel = []
    _back_az = []
    _f_stats = []

    _waveform_data_item = None

    _mp_pool = None

    def __init__(self, parent, pool):
        super().__init__()

        self._parent = parent
        self.settings = parent.settings

        self._mp_pool = pool

        self.buildUI()
        self.restoreSettings()

    def buildUI(self):

        self.make_toolbar()

        self.lhWidget = pg.GraphicsLayoutWidget()
        self.lhWidget.setMouseTracking(True)

        self.waveformPlot = IPPlotWidget.IPPlotWidget()
        self.waveformPlot.setLabel('left', 'Waveform')
        self.waveformPlot.hideButtons()

        self.fstatPlot = IPPlotWidget.IPPlotWidget(y_label_format='nonscientific', pickable=False)
        self.fstatPlot.setLogMode(y=True)
        self.fstatPlot.setYRange(0.1, 5)
        self.fstatPlot.enableAutoRange(axis=ViewBox.YAxis)
        self.fstatPlot.showGrid(x=True, y=True, alpha=0.3)
        self.fstatPlot.setLabel('left', 'F-Statistic')

        self.traceVPlot = IPPlotWidget.IPPlotWidget()
        self.traceVPlot.showGrid(x=True, y=True, alpha=0.3)
        self.traceVPlot.setYRange(0, 500)
        self.traceVPlot.setLabel('left', 'Trace Velocity (m/s)')

        self.backAzPlot = IPPlotWidget.IPPlotWidget()
        self.backAzPlot.showGrid(x=True, y=True, alpha=0.3)
        self.backAzPlot.setYRange(-180, 180)
        self.backAzPlot.setLabel('left', 'Back Azimuth (deg)')

        self.resultPlots = {'fplot': self.fstatPlot, 'tracePlot': self.traceVPlot, 'backPlot': self.backAzPlot}

        self.fstatPlot.setXLink(self.waveformPlot)
        self.traceVPlot.setXLink(self.waveformPlot)
        self.backAzPlot.setXLink(self.waveformPlot)

        self.lhWidget.addItem(self.waveformPlot)
        self.lhWidget.nextRow()
        self.lhWidget.addItem(self.fstatPlot)
        self.lhWidget.nextRow()
        self.lhWidget.addItem(self.traceVPlot)
        self.lhWidget.nextRow()
        self.lhWidget.addItem(self.backAzPlot)

        self._plot_list.append(self.waveformPlot)
        self._plot_list.append(self.fstatPlot)
        self._plot_list.append(self.traceVPlot)
        self._plot_list.append(self.backAzPlot)

        self.addCrosshairs()

        # --------------------------------------------
        # this is where I create the linear region item that specifies the current portion of waveform being evaluated

        self.timeRangeLRI = pg.LinearRegionItem()
        self.timeRangeLRI.setMovable(False)
        brush = QtGui.QBrush(QtGui.QColor(50, 50, 50, 50))
        self.timeRangeLRI.setBrush(brush)

        # --------------------------------------------
        # the slownessWidget will hold the slowness plot and the projection plot

        slownessWidget = pg.GraphicsLayoutWidget()

        # Create the slowness plot and its dataitem
        self.slownessPlot = IPPolarPlot.IPPolarPlot()
        self.spi = pg.ScatterPlotItem(pxMode=False, pen=pg.mkPen(None))

        # Create the slowness widget and its dataitem
        self.projectionPlot = IPPlotWidget.IPPlotWidget()
        self.projectionCurve = pg.PlotDataItem(x=[],
                                               y=[],
                                               pen=(60, 60, 60),
                                               symbol=None)
        self.max_projectionCurve = pg.PlotDataItem(x=[],
                                                   y=[],
                                                   pen=(180, 180, 180),
                                                   symbol=None)

        self.projectionPlot.showGrid(x=True, y=True, alpha=0.3)
        self.projectionPlot.addItem(self.max_projectionCurve)
        self.projectionPlot.addItem(self.projectionCurve)

        self.projectionPlot.setLabel('left', 'Avg. Beam Power')
        self.projectionPlot.setLabel('bottom', 'Azimuth')
        self.projectionPlot.setXRange(-180, 180)
        self.projectionPlot.getAxis('bottom').setTicks([[(-180, '-180'), (-90, '-90'), (0, '0'), (90, '90'), (180, '180')]])

        slownessWidget.addItem(self.slownessPlot)
        slownessWidget.nextRow()
        slownessWidget.addItem(self.projectionPlot)

        # ---------------------------------------------
        # the bottomWidget will hold the beamforming settings widget, and the detection widget...
        bottomWidget = QWidget()
        self.bottomTabWidget = QTabWidget()

        self.bottomSettings = IPBeamformingSettingsWidget.IPBeamformingSettingsWidget(self)
        self.detectionWidget = IPDetectionWidget.IPDetectionWidget(self)

        self.detectiontab_idx = self.bottomTabWidget.addTab(self.detectionWidget, 'Detections')
        self.bottomTabWidget.addTab(self.bottomSettings, 'Beamformer Settings')

        bottomLayout = QHBoxLayout()
        bottomLayout.addWidget(self.bottomTabWidget)

        bottomWidget.setLayout(bottomLayout)

        # ---------------------------------------------

        self.splitterTop = QSplitter(Qt.Horizontal)
        self.splitterTop.addWidget(self.lhWidget)
        self.splitterTop.addWidget(slownessWidget)
        self.splitterBottom = QSplitter(Qt.Horizontal)
        self.splitterBottom.addWidget(bottomWidget)

        # ---------------------------------------------

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.addWidget(self.splitterTop)
        self.main_splitter.addWidget(self.splitterBottom)

        self.main_layout = QVBoxLayout()
        self.main_layout.setMenuBar(self.toolbar)
        self.main_layout.addWidget(self.main_splitter)

        self.setLayout(self.main_layout)

        self.connectSignalsAndSlots()

        # Create a thread for the beamforming to run in
        self.bfThread = QThread()

    def make_toolbar(self):
        self.toolbar = QToolBar()

        # self.toolbar.setStyleSheet("QToolButton:!hover { padding-left:5px; padding-right:5px; padding-top:2px; padding-bottom:2px} QToolBar {background-color: rgb(0,107,166)}")
        # self.toolbar.setStyleSheet("QToolButton:!hover {background-color:blue} QToolButton:hover { background-color: lightgray }")

        toolButton_start = QToolButton()
        toolButton_stop = QToolButton()
        toolButton_clear = QToolButton()

        # if platform.system() != "Darwin":
        #     toolButton_start.setStyleSheet("QToolButton:!hover {background-color: #BDFFAB; margin-left:3px; margin-right:3px; padding-left:2px; padding-right:2px; border:1px solid #526F4A} QToolButton:hover {background-color: #D6FFC5; margin-left:3px; margin-right:3px; padding-left:2px; padding-right:2px; border:1px solid #526F4A}")
        #     toolButton_stop.setStyleSheet( "QToolButton:!hover {background-color: #FF7C7C; margin-left:3px; margin-right:3px; padding-left:2px; padding-right:2px; border:1px solid #793B3B} QToolButton:hover {background-color: #FFAFAF; margin-left:3px; margin-right:3px; padding-left:2px; padding-right:2px; border:1px solid #793B3B}")
        #     toolButton_clear.setStyleSheet("QToolButton:!hover {background-color: #FFF9D6; margin-left:3px; margin-right:3px; padding-left:2px; padding-right:2px; border:1px solid #787565} QToolButton:hover {background-color: #FEFFF6; margin-left:3px; margin-right:3px; padding-left:2px; padding-right:2px; border:1px solid #787565}")
        # else:
        #     self.toolbar.setStyleSheet("QToolButton:hover { background-color: lightgray; }")
        #     font = toolButton_start.font()
        #     font.setPointSize(14)
        #     toolButton_start.setFont(font)
        #     toolButton_start.setStyleSheet("QToolButton:!hover {color: green}")
        #     toolButton_stop.setFont(font)
        #     toolButton_stop.setStyleSheet("QToolButton:!hover {color: red}")
        #     toolButton_clear.setFont(font)

        self.runAct = QAction(QIcon.fromTheme("media-playback-start"), "Run Beamforming", self)
        self.runAct.triggered.connect(self.runBeamforming)
        toolButton_start.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolButton_start.setDefaultAction(self.runAct)

        self.stopAct = QAction(QIcon.fromTheme("media-playback-stop"), 'Stop', self)
        toolButton_stop.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolButton_stop.setDefaultAction(self.stopAct)

        self.clearAct = QAction(QIcon.fromTheme("edit-clear"), 'Clear', self)
        self.clearAct.triggered.connect(self.clearResultPlots)
        toolButton_clear.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolButton_clear.setDefaultAction(self.clearAct)

        self.toolbar.addWidget(toolButton_start)
        self.toolbar.addWidget(toolButton_stop)
        self.toolbar.addWidget(toolButton_clear)

    def addCrosshairs(self):
        # This adds the crosshairs that follow the mouse around, as well as the position labels which display the
        # UTC time in the top right corner of the plots
        for idx, my_plot in enumerate(self._plot_list):
            self._vlines.append(pg.InfiniteLine(angle=90, movable=False, pen='k'))
            self._hlines.append(pg.InfiniteLine(angle=0, movable=False, pen='k'))
            self._position_labels.append(pg.TextItem(color=(0, 0, 0), html=None, anchor=(1, 0)))
            self._value_labels.append(pg.TextItem(color=(0, 0, 0), html=None, anchor=(1, 0)))

            self._vlines[idx].setZValue(10)
            self._hlines[idx].setZValue(11)

            my_plot.addItem(self._vlines[idx], ignoreBounds=True)
            my_plot.addItem(self._hlines[idx], ignoreBounds=True)
            my_plot.addItem(self._position_labels[idx], ignoreBounds=True)
            my_plot.addItem(self._value_labels[idx], ignoreBounds=True)

    def connectSignalsAndSlots(self):
        # keep as many signal and slot connections as possible together in one place
        self.lhWidget.scene().sigMouseMoved.connect(self.myMouseMoved)
        self.detectionWidget.signal_detections_changed.connect(self.plotDetectionLines)

    def setStreams(self, streams):
        # keep a local reference for the streams that will be analyzied
        self._streams = streams

    def get_earliest_start_time(self):
        return self._parent.waveformWidget.plotViewer.pl_widget.earliest_start_time

    def plotDetectionLines(self):
        """
        This is the routine that draws the detection lines on the fstat plot

        Plotting detection lines makes no sense if there are no waveforms loaded to set the date and
        time for the plots.  One way to check this is to see if earliest_start_time is None,
        and if it is, bail until plots are loaded.

        If detections are determined to exist, cycle through them, create a new line, connect
        it to the appropriate slots, and add it to the fstat plot.
        """
        e_s_t = self.get_earliest_start_time()
        if e_s_t is None:
            return

        # the detectioningWidget is where the detection data lives
        detection_data = self.detectionWidget.get_data()

        # Data may have changed, so first clear out old detection lines, and then
        # we'll repopulate
        self.clearDetectionLines()

        # if no detections to plot, return
        if len(detection_data) == 0:
            return

        for detection in detection_data:

            starting_position = detection.get_peakF_UTCtime(type='obspy') - UTCDateTime(e_s_t)

            newDetectionLine = IPPickLine.IPPickLine(detection, starting_pos=starting_position)

            # These connections need to be made for each new detection line
            newDetectionLine.sigPickLineMoving.connect(self.detectionWidget.detectionLineMoving)
            newDetectionLine.sigPickLineMoved.connect(self.detectionWidget.detectionLineMoved)
            newDetectionLine.sigDeleteMe.connect(self.detectionWidget.delete_detection)

            newDetectionLine.sigCreateStartEndBars.connect(self.detectionWidget.createNewDetectionStartEndRegion)
            newDetectionLine.sigRemoveStartEndBars.connect(self.detectionWidget.removeDetectionStartEndRegion)
            newDetectionLine.sigStartEndBarsChanged.connect(self.detectionWidget.updateDetectionStartEnd)

            detection.setAssociatedPickLine(newDetectionLine)

            # add the detectionline to the fstat plot (or others eventually?) and
            # if it has one, a start/end linear region item
            self.fstatPlot.addItem(newDetectionLine)

            if newDetectionLine.startEndBars() is not None:
                self.fstatPlot.addItem(newDetectionLine.startEndBars())

    def clearDetectionLines(self):
        """
        Remove all detection lines from all plots, note that this does not remove detections
        from the list of detections in the detectionwidget
        """
        for plot in self._plot_list:
            for item in reversed(plot.items):
                if type(item) is IPPickLine.IPPickLine:
                    plot.removeItem(item)
                    del item
        self.clearDetectionStartEndRegions()

    def clearDetectionStartEndRegions(self):
        """
        Remove all start/end regions from all plots, note that this does not remove any info
        from the list of detections in the detectionwidget
        """
        for plot in self._plot_list:
            for item in reversed(plot.items):
                if type(item) is IPPickLine.IPStartEndRegionItem:
                    plot.removeItem(item)
                    del item

    @pyqtSlot(pg.PlotDataItem, tuple)
    def setWaveform(self, plotLine, region):
        if self._waveform_data_item is not None:
            self._waveform_data_item.clear()
        else:
            self._waveform_data_item = pg.PlotDataItem()

        # need to make a copy of the currently active plot and give it to the beamformingwidget for display
        self._waveform_data_item.setData(plotLine.xData, plotLine.yData)
        self._waveform_data_item.setPen(pg.mkPen(color=(100, 100, 100), width=1))
        self.waveformPlot.enableAutoRange(axis=ViewBox.YAxis)
        self.waveformPlot.addItem(self._waveform_data_item)
        self.waveformPlot.setXRange(region[0], region[1], padding=0)

    @pyqtSlot(tuple)
    def updateWaveformRange(self, new_range):
        self.waveformPlot.setXRange(new_range[0], new_range[1], padding=0)

    def myMouseMoved(self, evt):
        # This takes care of the crosshairs
        if len(self._plot_list) == 0:
            return

        e_s_t = self.get_earliest_start_time()
        if e_s_t is None:
            return

        for idx, my_plot in enumerate(self._plot_list):
            try:
                mousePoint = my_plot.vb.mapSceneToView(evt)
            except Exception:
                return
            self._vlines[idx].setPos(mousePoint.x())
            self._hlines[idx].setPos(mousePoint.y())

            if my_plot.sceneBoundingRect().contains(evt):
                myRange = my_plot.viewRange()
                vb = my_plot.getViewBox()
                _, sy = vb.viewPixelSize()  # this is to help position the valueLabels below the positionLabels

                self._position_labels[idx].setVisible(True)
                self._position_labels[idx].setPos(myRange[0][1], myRange[1][1])
                self._position_labels[idx].setText("UTC = {0}".format(e_s_t + mousePoint.x()))

                self._value_labels[idx].setVisible(True)
                self._value_labels[idx].setPos(myRange[0][1], myRange[1][1] - sy * self._position_labels[idx].boundingRect().height())
                self._value_labels[idx].setText("{}".format(round(mousePoint.y(), 4)))
            else:
                self._position_labels[idx].setVisible(False)
                self._value_labels[idx].setVisible(False)

    def getProject(self):
        return self._parent.getProject()

    def get_settings(self):
        return self._parent.settings

    def saveSettings(self):
        self._parent.settings.beginGroup('BeamFormingWidget')
        self._parent.settings.setValue("windowSize", self.size())
        self._parent.settings.setValue("windowPos", self.pos())
        self._parent.settings.setValue("bfmainSplitterSettings", self.main_splitter.saveState())
        self._parent.settings.setValue("splitterTopSettings", self.splitterTop.saveState())
        self._parent.settings.setValue("splitterBottomSettings", self.splitterBottom.saveState())
        self._parent.settings.endGroup()

    def restoreSettings(self):
        # Restore settings
        self._parent.settings.beginGroup('BeamFormingWidget')

        splitterTopSettings = self._parent.settings.value("splitterTopSettings")
        if splitterTopSettings:
            self.splitterTop.restoreState(splitterTopSettings)

        splitterBottomSettings = self._parent.settings.value("splitterBottomSettings")
        if splitterBottomSettings:
            self.splitterBottom.restoreState(splitterBottomSettings)

        splitterMainSettings = self._parent.settings.value("bfmainSplitterSettings")
        if splitterMainSettings:
            self.main_splitter.restoreState(splitterMainSettings)

        self._parent.settings.endGroup()

    def errorPopup(self, message):
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Information)
        msgBox.setText(message)
        msgBox.setWindowTitle("Oops...")
        msgBox.exec_()

    def runBeamforming(self):
        if self._streams is None:
            self.errorPopup('No data Loaded')
            return

        if self._parent.waveformWidget.get_inventory() is None:
            self.errorPopup('There are no stations loaded.  Station Lat and Lon information is required to do beamforming.')
            return

        if self._parent.waveformWidget.stationViewer.getStationCount() != self._streams.count():
            self.errorPopup('The number of stations is not equal to the number of waveforms. Each waveform must have a matching station with Lat./Lon. information in it.')
            return

        # we only want the slowness plot to show data at end of run
        self.spi.clear()
        self.spi.addPoints([])

        # First lets create some new curves, and add them to the pertinent plots
        self._t = []
        self._trace_vel = []
        self._back_az = []
        self._f_stats = []
        self.slownessX = np.array([])
        self.slownessY = np.array([])
        self.beam_power = np.array([])

        self.max_projection = None
        self.max_projection_curve = None
        self.max_projection_index = None

        # add the slownessPlotItem to the slowness plot
        self.slownessPlot.addItem(self.spi)

        self.resultData = {'t': self._t,
                           'tracev': self._trace_vel,
                           'backaz': self._back_az,
                           'fstats': self._f_stats,
                           'slownessX': self.slownessX,
                           'slownessY': self.slownessY,
                           'beampower': self.beam_power}

        method = self.bottomSettings.getMethod()
        if method == 'bartlett':
            symb = 'o'
            fcolor = (250, 0, 0)
            tcolor = (0, 250, 0)
            bcolor = (0, 0, 250)
        elif method == 'gls':
            symb = '+'
            fcolor = (220, 0, 0)
            tcolor = (0, 220, 0)
            bcolor = (0, 0, 220)
        elif method == 'bartlett_covar':
            symb = 't'
            fcolor = (190, 0, 0)
            tcolor = (0, 190, 0)
            bcolor = (0, 0, 190)
        elif method == 'capon':
            symb = 's'
            fcolor = (160, 0, 0)
            tcolor = (0, 160, 0)
            bcolor = (0, 0, 160)
        elif method == 'music':
            symb = 'd'
            fcolor = (130, 0, 0)
            tcolor = (0, 130, 0)
            bcolor = (0, 0, 130)

        self.fval_curve = pg.PlotDataItem(x=self._t,
                                          y=self._f_stats,
                                          pen=None,
                                          brush=fcolor,
                                          symbol=symb,
                                          symbolPen=fcolor,
                                          symbolBrush=fcolor,
                                          symbolSize='5')

        self.fval_curve.sigPointsClicked.connect(self.pointsClicked)
        self.fstatPlot.addItem(self.fval_curve)

        self.trace_curve = pg.PlotDataItem(x=self._t,
                                           y=self._trace_vel,
                                           pen=None,
                                           brush=tcolor,
                                           symbol=symb,
                                           symbolPen=tcolor,
                                           symbolBrush=tcolor,
                                           symbolSize='5')

        # self.trace_curve.sigPointsClicked.connect(self.pointsClicked)
        self.traceVPlot.addItem(self.trace_curve)

        self.backaz_curve = pg.ScatterPlotItem(x=self._t,
                                               y=self._back_az,
                                               pen=None,
                                               brush=bcolor,
                                               symbol=symb,
                                               symbolPen=bcolor,
                                               symbolBrush=bcolor,
                                               symbolSize='5')

        # self.backaz_curve.sigClicked.connect(self.pointsClicked)
        self.backAzPlot.addItem(self.backaz_curve)

        backaz_range = self.bottomSettings.getBackAzFreqRange()

        slowness_length = (750. - 300) / self.bottomSettings.getTraceVelResolution() * (backaz_range[1] - backaz_range[0]) / self.bottomSettings.getBackAzResolution()

        self._slowness_collection = []  # Clear this array for the new run

        self.bfWorker = BeamformingWorkerObject(self._streams,
                                                self.resultData,
                                                self.bottomSettings.getNoiseRange(),
                                                self.bottomSettings.getSignalRange(),
                                                self.bottomSettings.getFreqRange(),
                                                self.bottomSettings.getWinLength(),
                                                self.bottomSettings.getWinStep(),
                                                self.bottomSettings.getMethod(),
                                                self.bottomSettings.getNumSigs(),
                                                self.bottomSettings.getSubWinLength(),
                                                self._parent.waveformWidget.get_inventory(),
                                                self._mp_pool,
                                                self.bottomSettings.getBackAzResolution(),
                                                self.bottomSettings.getTraceVelResolution(),
                                                self.bottomSettings.getBackAzFreqRange())

        self.bfWorker.moveToThread(self.bfThread)

        self.signal_startBeamforming.connect(self.bfWorker.run)
        # self.stopButton.clicked.connect(self.bfWorker.stop)
        self.stopAct.triggered.connect(self.bfWorker.stop)

        self.bfWorker.signal_dataUpdated.connect(self.updateCurves)
        self.bfWorker.signal_slownessUpdated.connect(self.updateSlowness)
        self.bfWorker.signal_projectionUpdated.connect(self.updateProjection)
        self.bfWorker.signal_timeWindowChanged.connect(self.updateWaveformTimeWindow)
        self.bfWorker.signal_runFinished.connect(self.runFinished)

        # show the time range
        self.waveformPlot.addItem(self.timeRangeLRI)
        self.timeRangeLRI.setRegion((self.bottomSettings.getSignalRange()[0], self.bottomSettings.getSignalRange()[0] + self.bottomSettings.getWinLength()))

        # disable some buttons
        # self.startButton.setEnabled(False)
        self.runAct.setEnabled(False)
        # self.clearButton.setEnabled(False)
        self.clearAct.setEnabled(False)

        # reset the run_step
        self.run_step = 0

        # start the thread
        self.bfThread.start()

        self.signal_startBeamforming.emit()

    def pointsClicked(pdi, points_clicked):
        print('type(pdi) = {}'.format(type(pdi)))
        print('type(points_clicked) = {}'.format(type(points_clicked)))
        for idx, point in enumerate(points_clicked):
            print('{}: x={}, y={}'.format(idx, point.x(), point.y()))

    def updateCurves(self):
        # print('ttype = {}, fstatstype = {}'.format(type(self.t), type(self.fstats)))
        self.fval_curve.setData(self._t, self._f_stats)
        self.trace_curve.setData(self._t, self._trace_vel)
        self.backaz_curve.setData(self._t, self._back_az)

    @pyqtSlot(np.ndarray)
    def updateSlowness(self, slowness):
        # draw the slowness plot
        # first make a new scatterplotitem to hold the points

        view_update = False
        if view_update:
            self.dots = []
            method = self.bottomSettings.getMethod()

            max_slowness = np.max(slowness[:, -1])
            min_slowness = np.min(slowness[:, -1])

            # maxLine = IPLine.IPLine()
            # maxLine.setLine(0,0,slowness[idx_max, 0], slowness[idx_max, 1])

            if method == "music" or method == "capon":
                scaled_slowness = 100 * (1.0 - (slowness[:, -1] - min_slowness) / (max_slowness - min_slowness))
            elif method == "gls":
                scaled_slowness = 100 * (1.0 - (slowness[:, -1]) / np.max(slowness[:, -1]))

            for i in range(slowness.shape[0]):

                if method == "bartlett_covar" or method == "bartlett":
                    brush = pg.intColor(100 * (slowness[i, -1]), hues=100, values=1)

                else:
                    brush = pg.intColor(scaled_slowness[i], hues=100, values=1)

                self.dots.append({'pos': (slowness[i, 0], slowness[i, 1]), 'brush': brush, 'size': 0.0002})

            self.spi.clear()
            self.spi.addPoints(self.dots)

        # self.slownessPlot.addItem(maxLine)
        save_slowness = True
        if save_slowness:
            self._slowness_collection.append(slowness[:])
            slowness = []

    def plot_slowness_at_idx(self, idx):
        self.dots = []

        slowness = self._slowness_collection[idx]

        method = self.bottomSettings.getMethod()
        if method == "music" or method == "capon":
            max_slowness = np.max(slowness[:, -1])
            min_slowness = np.min(slowness[:, -1])
            scaled_slowness = 100 * (1.0 - (slowness[:, -1] - min_slowness) / (max_slowness - min_slowness))
        elif method == "gls":
            scaled_slowness = 100 * (1.0 - (slowness[:, -1]) / np.max(slowness[:, -1]))

        for i in range(slowness.shape[0]):
            if method == "bartlett_covar" or method == "bartlett":
                brush = pg.intColor(100 * (slowness[i, -1]), hues=100, values=1)

            else:
                brush = pg.intColor(scaled_slowness[i], hues=100, values=1)

            self.dots.append({'pos': (slowness[i, 0], slowness[i, 1]), 'brush': brush, 'size': 0.0002})

        self.spi.clear()
        self.spi.addPoints(self.dots)

    @pyqtSlot(np.ndarray, np.ndarray)
    def updateProjection(self, projection, avg_beam_power):

        self.projectionCurve.setData(projection)
        if self.max_projection is None:
            self.max_projection = np.amax(projection[:, 1])
            self._max_projection_data = projection.copy()
            self.max_projectionCurve.setData(projection)
            self.max_projection_index = self.run_step
        else:
            _max = np.amax(projection[:, 1])
            if _max > self.max_projection:
                self.max_projection = _max
                self._max_projection_data = projection.copy()
                self.max_projectionCurve.setData(self._max_projection_data)
                self.max_projection_index = self.run_step

        method = self.bottomSettings.getMethod()
        if method == "bartlett_covar" or method == "bartlett" or method == "gls":
            self.projectionPlot.setYRange(0, 1)
        else:
            pass

        self.projectionPlot.setXRange(-180, 180)

    @pyqtSlot(tuple)
    def updateWaveformTimeWindow(self, window):
        # this will update the linearregionitem that displays the timewindow currently evaluated
        self.timeRangeLRI.setRegion(window)
        self.run_step += 1

    @pyqtSlot()
    def runFinished(self):
        if len(self._f_stats) < 1:
            # we haven't finished a single step, so bail out
            return

        # self.startButton.setEnabled(True)
        self.runAct.setEnabled(True)
        # self.clearButton.setEnabled(True)
        self.clearAct.setEnabled(True)

        # find peak F-value location and the corresponding back azimuth and trace velocity
        f_max = max(self._f_stats)
        f_max_idx = self._f_stats.index(f_max)
        f_max_time = self._t[f_max_idx]

        _back_az_at_max = self._back_az[f_max_idx]
        _trace_vel_at_max = self._trace_vel[f_max_idx]

        # make the slowness plot show the data at the time of fstat max
        self.plot_slowness_at_idx(f_max_idx)

        # make the projection plot shot the data at the time of fstat max
        if self._max_projection_data is not None:
            self.projectionCurve.setData(self._max_projection_data)
            self.projectionPlot.addItem(self.projectionCurve)

        # move the waveform time region to reflect the location of the f_max
        t_range = self.timeRangeLRI.getRegion()
        t_half_width = (t_range[1] - t_range[0]) / 2.
        t_region = [f_max_time - t_half_width, f_max_time + t_half_width]
        self.timeRangeLRI.setRegion(t_region)

        # add a detection at the place were fstat was a maximum
        center = self._parent.waveformWidget.stationViewer.get_current_center()

        self.detectionWidget.newDetection('',
                                          UTCDateTime(self.get_earliest_start_time()) + f_max_time,
                                          f_max,
                                          _trace_vel_at_max,
                                          _back_az_at_max,
                                          center[0],
                                          center[1],
                                          elev=center[2],
                                          element_cnt=len(self._streams),
                                          method=self.bottomSettings.getMethod(),
                                          fr=self.bottomSettings.getFreqRange())

        self.bottomTabWidget.setCurrentIndex(self.detectiontab_idx)

    def clearResultPlots(self):
        self.fstatPlot.clear()
        self.fstatPlot.setYRange(0.1, 1)
        self.fstatPlot.enableAutoRange(axis=ViewBox.YAxis)
        self._f_stats.clear()

        self.backAzPlot.clear()
        self._back_az.clear()

        self.traceVPlot.clear()
        self._trace_vel.clear()

        self.projectionCurve.clear()
        self.max_projectionCurve.clear()

        self.slownessPlot.clear()
        self.slownessPlot.drawPlot()

        self.spi.clear()

        self._t.clear()

        # clearing removes the crosshairs, so lets put them back
        self.addCrosshairs()

    def clearWaveformPlot(self):
        self.waveformPlot.clear()
        self.waveformPlot.setYRange(0, 1)
        self.clearResultPlots()     # it doesn't make sense to have results and no waveform


class BeamformingWorkerObject(QtCore.QObject):

    signal_runFinished = pyqtSignal()
    signal_dataUpdated = pyqtSignal()
    signal_slownessUpdated = pyqtSignal(np.ndarray)
    signal_projectionUpdated = pyqtSignal(np.ndarray, np.ndarray)
    signal_timeWindowChanged = pyqtSignal(tuple)

    def __init__(self, streams, resultData, noiseRange, sigRange, freqRange,
                 win_length, win_step, method, signal_cnt, sub_window_len,
                 inventory, pool, back_az_resol, tracev_resol,
                 back_az_freqs):
        super().__init__()
        self.resultData = resultData
        self.streams = streams
        self.noiseRange = noiseRange
        self.sigRange = sigRange
        self.freqRange = freqRange
        self.win_length = win_length
        self.win_step = win_step
        self.method = method
        self.signal_cnt = signal_cnt
        self._inv = inventory
        self._pool = pool
        self._back_az_resolution = back_az_resol
        self._back_az_startF = back_az_freqs[0]
        self._back_az_endF = back_az_freqs[1]
        self._trace_v_resolution = tracev_resol

        self.threadStopped = True

        if sub_window_len is None:
            self.sub_window_len = self.win_length
        else:
            self.sub_window_len = sub_window_len

    @pyqtSlot()
    def stop(self):
        self.threadStopped = True

    def errorPopup(self, message):
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Information)
        msgBox.setText(message)
        msgBox.setWindowTitle("Oops...")
        msgBox.exec_()

    @pyqtSlot()
    def run(self):

        self.threadStopped = False

        back_az_vals = np.arange(self._back_az_startF, self._back_az_endF, self._back_az_resolution)
        # note if you make the 300 and 750 into a control, then you need to do that when you calculate the slowness size as well
        trc_vel_vals = np.arange(300.0, 750.0, self._trace_v_resolution)

        latlon = []

        # we want to build the latlon array so that it has the same order as the streams
        location_count = 0
        for trace in self.streams:

            id_bits = trace.id.split('.')
            # TODO... this is a bit of a hack to help deal with horrible people who make sac files with absent network/station codes
            #         see for instance, sac_to_inventory for the other half of this
            if id_bits[0] == '':
                id_bits[0] = '###'
            if id_bits[1] == '':
                id_bits[1] = '###'
            stream_station_id = id_bits[0] + '.' + id_bits[1]

            for network in self._inv.networks:
                for station in network.stations:
                    station_id = network.code + '.' + station.code
                    if station_id == stream_station_id:
                        latlon.append([station.latitude, station.longitude])
                        location_count += 1

        if location_count != len(self.streams):
            self.errorPopup("Trace IDs don't seem to match with the inventory station list. Please check each carefully and make sure you have a matching inventory entry for each stream \\Aborting")
            return

        x, t, t0, geom = beamforming_new.stream_to_array_data(self.streams, latlon)
        M, _ = x.shape

        # define slowness_grid... these are the x,y values that correspond to the beam_power values
        slowness = beamforming_new.build_slowness(back_az_vals, trc_vel_vals)
        delays = beamforming_new.compute_delays(geom, slowness)
        # slowness = slowness_grid.copy()

        _, S, _ = beamforming_new.fft_array_data(x, t, window=[self.noiseRange[0], self.noiseRange[1]], sub_window_len=self.sub_window_len)
        ns_covar_inv = np.empty_like(S)
        for n in range(S.shape[2]):
            S[:, :, n] += 1.0e-3 * np.mean(np.diag(S[:, :, n])) * np.eye(S.shape[0])
            ns_covar_inv[:, :, n] = np.linalg.inv(S[:, :, n])

        # Run beamforming in windowed data and write to file

        for self.window_start in np.arange(self.sigRange[0], self.sigRange[1], self.win_step):

            # In order to catch the stop button clicks, need to force process the events
            QCoreApplication.processEvents()

            if self.threadStopped:
                self.signal_runFinished.emit()
                return

            if self.window_start + self.win_length > self.sigRange[1]:
                self.signal_runFinished.emit()
                return

            self.signal_timeWindowChanged.emit((self.window_start, self.window_start + self.win_length))

            X, S, f = beamforming_new.fft_array_data(x, t, window=[self.window_start, self.window_start + self.win_length], sub_window_len=self.sub_window_len)

            beam_power = beamforming_new.run(X,
                                             S,
                                             f,
                                             geom,
                                             delays,
                                             self.freqRange,
                                             method=self.method,
                                             normalize_beam=True,
                                             signal_cnt=self.signal_cnt,
                                             pool=self._pool,
                                             ns_covar_inv=ns_covar_inv)

            # Compute relative beam power and average over frequencies
            avg_beam_power = np.average(beam_power, axis=0)

            # Analyze distribution to find peaks and compute the f-value of the peak
            peaks = beamforming_new.find_peaks(beam_power, back_az_vals, trc_vel_vals, signal_cnt=self.signal_cnt)

            self.resultData['t'].append(self.window_start + self.win_length / 2.0)
            self.resultData['backaz'].append(peaks[0][0])
            self.resultData['tracev'].append(peaks[0][1])

            if self.method == "bartlett_covar" or self.method == "bartlett" or self.method == "gls":
                fisher_val = peaks[0][2] / (1.0 - peaks[0][2]) * (M - 1)
                self.resultData['fstats'].append(fisher_val)

            else:
                self.resultData['fstats'].append(peaks[0][2])

            # Data is updated, signal plots to change
            self.signal_dataUpdated.emit()

            # Compute back azimuth projection of distribution
            az_proj, _ = beamforming_new.project_beam(beam_power, back_az_vals, trc_vel_vals)
            projection = np.c_[back_az_vals, az_proj]

            # signal projection plot to update
            self.signal_projectionUpdated.emit(projection, avg_beam_power)

            self.signal_slownessUpdated.emit(np.c_[slowness, avg_beam_power])