import pyqtgraph as pg
import numpy as np

from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (QWidget, QGridLayout, QMessageBox, QSplitter, QTabWidget)

from InfraView.widgets import (IPFilterSettingsWidget,
                               IPPlotViewer,
                               IPPlotWidget,
                               IPPSDWidget,
                               IPStationView,
                               IPStatsView)

import copy

import obspy
from obspy.core.stream import Stream
from obspy.core.inventory import Inventory, Network, Station, Channel, Site


class IPWaveformWidget(QWidget):

    """ The IPWaveformWidget holds the waveform and inventory data.  The IPPlotViewer plots the data,
    The IPFilterSettingsWidget holds the filter settings and tells the WaveformWidget when to update that
    data.  The IPStatsView displays the trace data, and the IPStationView displays the station data.
    """

    _sts = None             # streams
    _sts_filtered = None    # filtered streams
    _inv = None             # inventory

    def __init__(self, parent=None, pool=None, project=None):
        super().__init__(parent)

        self._parent = parent
        self.settings = parent.settings
        self._mp_pool = pool

        self.buildUI()

    def buildUI(self):

        self.stationViewer = IPStationView.IPStationView(self)
        self.statsViewer = IPStatsView.IPStatsView(self)
        self.info_tabs = QTabWidget()
        self.info_tabs.addTab(self.statsViewer, 'Trace Info')
        self.info_tabs.addTab(self.stationViewer, 'Station Info')

        self.filterSettingsWidget = IPFilterSettingsWidget.IPFilterSettingsWidget(self)
        self.spectraWidget = IPPSDWidget.IPPSDWidget(self)

        self.plotViewer = IPPlotViewer.IPPlotViewer(self, self.filterSettingsWidget)

        self.lh_splitter = QSplitter(Qt.Vertical)
        self.lh_splitter.addWidget(self.plotViewer)
        self.lh_splitter.addWidget(self.info_tabs)

        self.rh_splitter = QSplitter(Qt.Vertical)
        self.rh_splitter.setStyleSheet("QSplitter::handle{ background-color: #444444}")
        self.rh_splitter.setHandleWidth(2)
        self.rh_splitter.addWidget(self.spectraWidget)
        self.rh_splitter.addWidget(self.filterSettingsWidget)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self.lh_splitter)
        self.main_splitter.addWidget(self.rh_splitter)

        main_layout = QGridLayout()
        main_layout.addWidget(self.main_splitter)

        self.setLayout(main_layout)

        self.connect_signals_and_slots()

    def connect_signals_and_slots(self):
        self.filterSettingsWidget.sig_filter_changed.connect(self.update_filtered_data)
        self.filterSettingsWidget.sig_filter_display_changed.connect(self.plotViewer.show_hide_lines)

        self.statsViewer.removeTrace.connect(self.remove_trace)

        self.plotViewer.lr_settings_widget.noiseSpinsChanged.connect(self._parent.beamformingWidget.bottomSettings.setNoiseValues)
        self.plotViewer.lr_settings_widget.signalSpinsChanged.connect(self._parent.beamformingWidget.bottomSettings.setSignalValues)
        self.plotViewer.lr_settings_widget.signalSpinsChanged.connect(self._parent.beamformingWidget.updateWaveformRange)
        self.plotViewer.pl_widget.sig_active_plot_changed.connect(self.update_widgets)

        self.spectraWidget.f1_Spin.valueChanged.connect(self._parent.beamformingWidget.bottomSettings.setFmin)
        self.spectraWidget.f2_Spin.valueChanged.connect(self._parent.beamformingWidget.bottomSettings.setFmax)
        self.spectraWidget.psdPlot.getFreqRegion().sigRegionChanged.connect(self._parent.beamformingWidget.bottomSettings.setFreqValues)

    def get_project(self):
        return self._parent.getProject()

    def errorPopup(self, message):
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Information)
        msgBox.setText(message)
        msgBox.setWindowTitle("Oops...")
        msgBox.exec_()


    @pyqtSlot(obspy.core.stream.Stream, obspy.core.inventory.inventory.Inventory)
    def appendTraces(self, newTraces, newInventory):
        if newTraces is None:
            return

        if self._sts is None:
            self._sts = newTraces
        else:
            self._sts += newTraces

        if newInventory is None:
            return

        if self._inv is None:
            self._inv = newInventory
        else:
            self._inv += newInventory

        for trace in self._sts:
            trace.data = trace.data - np.mean(trace.data)
            self._sts.merge(fill_value=0)

        # it's possible, if the open failed, that self.waveformWidget._sts is still None, so if it is, bail out
        # if not populate the trace stats viewer and plot the traces
        if self._sts is not None:

            #TODO...is there a better way of doing this?
            self._parent.beamformingWidget.setStreams(self._sts)

            self.stationViewer.setInventory(self._inv)
            self.statsViewer.setStats(self._sts)
            # self.locationWidget.update_station_markers(self._inv)

            self.update_streams(self._sts)
            self.update_inventory(self._inv)

            self._parent.setStatus("Ready", 5000)
        else:
            return

    @pyqtSlot(obspy.core.stream.Stream, obspy.core.inventory.inventory.Inventory)
    def replaceTraces(self, newTraces, newInventory):
        # same as append, just clear out the old traces and inventory first
        self._sts = None
        self._inv = None
        self.stationViewer.setInventory(self._inv)

        self.appendTraces(newTraces, newInventory)

    def get_streams(self):
        return self._sts

    def get_filtered_streams(self):
        return self._sts_filtered

    def get_inventory(self):
        return self._inv

    def set_inventory(self, new_inv):
        self._inv = new_inv

    def getTraceName(self, trace):
        traceName = trace.stats['network'] + '.' + trace.stats['station'] + \
            '.' + trace.stats['location'] + '.' + trace.stats['channel']
        return traceName

    def get_earliest_start_time(self):
        return self.plotViewer.pl_widget.earliest_start_time

    @pyqtSlot(Stream)
    def update_streams(self, new_stream):
        # this should be called when you load new streams, or remove traces
        self._sts = new_stream
        self._sts_filtered = self.filter_stream(self._sts,
                                                self.filterSettingsWidget.get_filter_settings())
        self.plotViewer.set_streams(self._sts,
                                    self._sts_filtered,
                                    self.filterSettingsWidget.get_filter_display_settings())

        self.statsViewer.setStats(new_stream)

    @pyqtSlot(Inventory)
    def update_inventory(self, new_inventory):
        self._inv = new_inventory
        self.stationViewer.setInventory(self._inv)

    @pyqtSlot(dict)
    def update_filtered_data(self, filter_settings):

        # this should be called when settings in the filter widget are changed
        if self._sts is None:
            # Nothing to filter, clear out the filtered_streams and return
            self._sts_filtered = None
            return

        self._sts_filtered = self.filter_stream(self._sts,
                                                filter_settings)

        self.plotViewer.pl_widget.update_filtered_line_data(self._sts_filtered)
        index = self.plotViewer.pl_widget.get_active_plot()
        self.update_widgets(index, 
                            self.plotViewer.get_plot_lines(), 
                            self.plotViewer.get_filtered_plot_lines(), 
                            self.plotViewer.pl_widget.plot_list[index].getSignalRegionRange())

    def filter_stream(self, stream, cfs):

        # cfs: Current Filter Settings
        if stream is None:
            # nothing to do
            return None

        filtered_stream = Stream()

        for trace in stream:

            filtered_trace = trace.copy()

            filtType = cfs['type']

            if filtType == 'High Pass':
                try:
                    filtered_trace.filter('highpass',
                                        freq=cfs['F_high'],
                                        corners=cfs['order'],
                                        zerophase=cfs['zphase'])
                except ValueError as e:
                    self.errorPopup(str(e))

            elif filtType == 'Low Pass':
                try:
                    filtered_trace.filter('lowpass',
                                        freq=cfs['F_low'],
                                        corners=cfs['order'],
                                        zerophase=cfs['zphase'])
                except ValueError as e:
                    self.errorPopup(str(e))

            elif filtType == 'Band Pass':
                try:
                    filtered_trace.filter('bandpass',
                                        freqmin=cfs['F_high'],
                                        freqmax=cfs['F_low'],
                                        corners=cfs['order'],
                                        zerophase=cfs['zphase'])
                except ValueError as e:
                    self.errorPopup(str(e))

            else:
                print(filtType + ' filter not implemented yet')
                return
            filtered_stream += filtered_trace

        return filtered_stream

    def saveSettings(self):
        self._parent.settings.beginGroup('WaveformWidget')
        self._parent.settings.setValue("main_splitterSettings", self.main_splitter.saveState())
        self._parent.settings.setValue("rh_splitterSettings", self.rh_splitter.saveState())
        self._parent.settings.setValue("lh_splitterSettings", self.lh_splitter.saveState())
        self._parent.settings.endGroup()

    def restoreSettings(self):
        # Restore settings
        self._parent.settings.beginGroup('WaveformWidget')

        main_splitterSettings = self._parent.settings.value("main_splitterSettings")
        if main_splitterSettings:
            self.main_splitter.restoreState(main_splitterSettings)

        rh_splitterSettings = self._parent.settings.value("rh_splitterSettings")
        if rh_splitterSettings:
            self.rh_splitter.restoreState(rh_splitterSettings)

        lh_splitterSettings = self._parent.settings.value("lh_splitterSettings")
        if lh_splitterSettings:
            self.lh_splitter.restoreState(lh_splitterSettings)

        self._parent.settings.endGroup()

    @QtCore.pyqtSlot(str)
    def remove_trace(self, trace_id):

        for trace in self._sts.select(id=trace_id):
            self._sts.remove(trace)
            self.removeStation(trace.stats['network'], trace.stats['station'])

        self.statsViewer.setStats(self._sts)

        if len(self._sts) == 0:
            self._sts = None

        self.update_streams(self._sts)

    def removeStation(self, net_id, station_id):

        if self._inv is not None:
            try:
                self._inv = self.inv_remove(self._inv, network=net_id, station=station_id)

            except AttributeError as e:
                print(e)

            self.stationViewer.setInventory(self._inv)

    def inv_remove(self,
                   _inventory,
                   network='*',
                   station='*',
                   location='*',
                   channel='*',
                   keep_empty=False):

        selected = _inventory.select(network=network,
                                     station=station,
                                     location=location,
                                     channel=channel)

        selected_networks = [net for net in selected]
        selected_stations = [sta for net in selected_networks for sta in net]
        selected_channels = [cha for net in selected_networks
                             for sta in net for cha in sta]

        networks = []
        for net in _inventory:
            if net in selected_networks and station == '*' and \
                    location == '*' and channel == '*':
                continue
            stations = []
            for sta in net:
                if sta in selected_stations and location == '*' and channel == '*':
                    continue
                channels = []
                for cha in sta:
                    if cha in selected_channels:
                        continue
                    channels.append(cha)
                if not channels and not keep_empty:
                    continue
                sta = copy.copy(sta)
                sta.channels = channels
                stations.append(sta)

            if not stations and not keep_empty:
                continue
            net = copy.copy(net)
            net.stations = stations
            networks.append(net)

        return obspy.core.inventory.inventory.Inventory(networks, 'source')

    def clearWaveforms(self):

        # empty out the streams
        self._sts = None
        self._sts_filtered = None

        # empty out the child widgets
        self.statsViewer.clear()
        self.stationViewer.clear()
        self.plotViewer.clear()
        self.spectraWidget.clearPlot()

    @pyqtSlot(object)
    def update_signal_PSD(self, signal_region_item):

        if len(self._sts) == 0:
            self.spectraWidget.clearPlot()
            return

        signal_region = signal_region_item.getRegion()

        active_plot = self.plotViewer.pl_widget.get_active_plot()

        # calculate the PSD of the ---------------------------tart and finish
        dt = self._sts[active_plot].stats.delta
        start = int(signal_region[0] / dt)
        stop = int(signal_region[1] / dt)

        self.spectraWidget.updateSignalPSD(self._sts[active_plot][start:stop])

    @pyqtSlot(object)
    def update_noise_PSD(self, noise_region_item):

        if len(self._sts) == 0:
            self.spectraWidget.clearPlot()
            return

        noise_region = noise_region_item.getRegion()

        active_plot = self.plotViewer.pl_widget.get_active_plot()

        # calculate the PSD of the data in the current noise region
        dt = self._sts[active_plot].stats.delta
        start = int(noise_region[0] / dt)
        stop = int(noise_region[1] / dt)

        self.spectraWidget.updateNoisePSD(self._sts[active_plot][start:stop])


    @pyqtSlot(int, list, list, tuple)
    def update_widgets(self, index, lines, filtered_lines, signal_region):
        if len(self._sts) > 0:
            self.spectraWidget.set_title(self._sts[index].id)
            self.spectraWidget.set_fs(self._sts[index].stats.sampling_rate)

            noise_region_item = self.plotViewer.pl_widget.plot_list[index].getNoiseRegion()
            noise_region_item.sigRegionChanged.emit(noise_region_item)
            signal_region_item = self.plotViewer.pl_widget.plot_list[index].getSignalRegion()
            signal_region_item.sigRegionChanged.emit(signal_region_item)

            current_filter_display_settings = self.filterSettingsWidget.get_filter_display_settings()
            if current_filter_display_settings['apply']:
                self._parent.beamformingWidget.setWaveform(filtered_lines[index], signal_region)
            else:
                self._parent.beamformingWidget.setWaveform(lines[index], signal_region)

        else:
            self.spectraWidget.set_title('...')