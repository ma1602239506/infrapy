import os

from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QLayout, QMessageBox,
                             QPushButton, QWidget, QTextEdit, QTabWidget, QFileDialog,
                             QVBoxLayout)
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5.QtGui import QIcon

from PyQt5.QtCore import pyqtSignal, pyqtSlot, QDir, QSettings

import obspy
from obspy import read_inventory
from obspy.core.inventory import Inventory, Network, Station, Channel, Site
import lxml.etree

from InfraView.widgets import IPStationMatchDialog


class IPStationView(QWidget):

    # class to ease the process of displaying the obspy inventory list
    __savefile = None

    inventory_changed = pyqtSignal(obspy.core.inventory.inventory.Inventory)
    inventory_cleared = pyqtSignal()

    def __init__(self, parent):
        super().__init__()

        self.__parent = parent
        self.buildUI()

        # self.station_TabWidget.setTabsClosable(True)
        # self.station_TabWidget.tabCloseRequested.connect(self.closeMyTab)
        self.show()

    def buildUI(self):

        self.buildIcons()

        self.station_TabWidget = QTabWidget()
        self.station_TabWidget.setSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Expanding)

        self.clearButton = QPushButton(' Clear Stations')
        self.clearButton.setIcon(self.clearIcon)
        self.saveButton = QPushButton(' Save Stations')
        self.saveButton.setIcon(self.saveIcon)
        self.saveAsButton = QPushButton(' Save Stations As...')
        self.saveAsButton.setIcon(self.saveAsIcon)

        self.loadButton = QPushButton(' Load...')
        self.loadButton.setIcon(self.openIcon)

        self.reconcileButton = QPushButton(' Reconcile Stations')
        self.reconcileButton.setToolTip(self.tr('Attempt to download stations for current waveforms'))

        savebuttonGroup = QWidget()
        savebuttonLayout = QGridLayout()

        savebuttonGroup.setLayout(savebuttonLayout)
        savebuttonLayout.addWidget(self.loadButton, 1, 0)
        savebuttonLayout.addWidget(self.clearButton, 1, 1)
        savebuttonLayout.addWidget(self.saveButton, 0, 0)
        savebuttonLayout.addWidget(self.saveAsButton, 0, 1)
        savebuttonLayout.addWidget(self.reconcileButton, 2, 1)
        savebuttonLayout.setSizeConstraint(QLayout.SetFixedSize)

        verticalLayout = QVBoxLayout()
        verticalLayout.addWidget(savebuttonGroup)
        verticalLayout.addStretch()

        mainLayout = QHBoxLayout()
        mainLayout.addWidget(self.station_TabWidget)
        mainLayout.addLayout(verticalLayout)

        # go ahead and make an instance of the matchDialog for later use
        self.matchDialog = IPStationMatchDialog.IPStationMatchDialog()

        self.setLayout(mainLayout)
        self.connectSignalsandSlots()

    def buildIcons(self):
        self.clearIcon = QIcon.fromTheme("edit-clear")
        self.openIcon = QIcon.fromTheme("document-open")
        self.saveIcon = QIcon.fromTheme("document-save")
        self.saveAsIcon = QIcon.fromTheme("document-save-as")

    def connectSignalsandSlots(self):
        self.clearButton.clicked.connect(self.clear)
        self.saveButton.clicked.connect(self.saveStations)
        self.saveAsButton.clicked.connect(self.saveStationsAs)
        self.loadButton.clicked.connect(self.loadStations)
        self.reconcileButton.clicked.connect(self.reconcileStations)

    def setInventory(self, _inventory):

        if _inventory is None:
            self.clear()
            return

        self.inventory_changed.emit(_inventory)

        tab_names = []

        self.station_TabWidget.clear()

        for network in _inventory.networks:
            for station in network.stations:

                names = []
                if len(station.channels) > 0:
                    for channel in station.channels:
                        name = network.code + '.' + station.code + '.' + channel.location_code

                        if name not in tab_names:
                            # Ok, need at least one, so lets assemble the interesting station info for display
                            newStationEdit = QTextEdit()
                            contents = station.get_contents()
                            ret = ("<b>Network:</b> {network_code}<br/>"
                                   "<b>Station:</b> {station_name}<br/>"
                                   "<b>Station Code:</b> {station_code}<br/>"
                                   "<b>Location Code:</b> {location_code}</br>"
                                   "<b>Channel Count:</b> {selected}/{total} (Selected/Total)<br/>"
                                   "<Available Dates:</b> {start_date} - {end_date}<br/>"
                                   "<b>Access:</b> {restricted} {alternate_code}{historical_code}<br/>"
                                   "<b>Latitude:</b> {lat:.2f}<br/>"
                                   "<b>Longitude:</b> {lng:.2f}<br/>"
                                   "<b>Elevation:</b> {elevation:.1f} m<br/>")
                            ret = ret.format(
                                network_code=network.code,
                                station_name=contents["stations"][0],
                                station_code=station.code,
                                location_code=channel.location_code,
                                selected=station.selected_number_of_channels,
                                total=station.total_number_of_channels,
                                start_date=str(station.start_date),
                                end_date=str(station.end_date) if station.end_date else "",
                                restricted=station.restricted_status,
                                lat=station.latitude, lng=station.longitude, elevation=station.elevation,
                                alternate_code="Alternate Code: %s " % station.alternate_code if station.alternate_code else "",
                                historical_code="Historical Code: %s " % station.historical_code if station.historical_code else "")

                            newStationEdit.setHtml(ret)
                            self.station_TabWidget.addTab(newStationEdit, name)
                else:
                    name = network.code + '.' + station.code

                    if name not in tab_names:
                        # Ok, need at least one, so lets assemble the interesting station info for display
                        newStationEdit = QTextEdit()
                        contents = station.get_contents()
                        ret = ("<b>Network Code:</b> {network_code} <br/>"
                               "<b>Station Code:</b> {station_code} <br/>"
                               "<b>Location Code:</b> {location_code} </br>"
                               "<b>Channel Count:</b> {selected}/{total} (Selected/Total)<br/>"
                               "<Available Dates:</b> {start_date} - {end_date}<br/>"
                               "<b>Access:</b> {restricted} {alternate_code}{historical_code}<br/>"
                               "<b>Latitude:</b> {lat:.2f}<br/>"
                               "<b>Longitude:</b> {lng:.2f}<br/>"
                               "<b>Elevation:</b> {elevation:.1f} m<br/>")
                        ret = ret.format(
                            network_code=network.code,
                            station_name=contents["stations"][0],
                            station_code=station.code,
                            location_code='',
                            selected=station.selected_number_of_channels,
                            total=station.total_number_of_channels,
                            start_date=str(station.start_date),
                            end_date=str(station.end_date) if station.end_date else "",
                            restricted=station.restricted_status,
                            lat=station.latitude, lng=station.longitude, elevation=station.elevation,
                            alternate_code="Alternate Code: %s " % station.alternate_code if station.alternate_code else "",
                            historical_code="Historical Code: %s " % station.historical_code if station.historical_code else "")

                        newStationEdit.setHtml(ret)
                        self.station_TabWidget.addTab(newStationEdit, network.code + '.' + station.code)
        return

    def getStationCount(self):
        cnt = 0
        inventory = self.__parent.get_inventory()
        for network in inventory.networks:
            for station in network.stations:
                cnt += 1
        return cnt

    @QtCore.pyqtSlot(int)
    def closeMyTab(self, idx):
        self.station_TabWidget.removeTab(idx)

    def clear(self):
        for i in range(self.station_TabWidget.count()):
            self.station_TabWidget.removeTab(0)
 
        self.__parent.set_inventory(None)

        # now signal to the application that the inventory needs to be cleared
        self.inventory_cleared.emit()

    def saveStations(self):
        inventory = self.__parent.get_inventory()
        if inventory is None:
            self.errorPopup('Oops... There are no stations to save')
            return
        # if there is no current filename, prompt for one...
        # TODO: if there is an open project, default to that
        if self.__savefile is None:
            self.saveStationsAs()
        else:
            inventory.write(self.__savefile[0], format='stationxml', validate=True)
            path = os.path.dirname(self.__savefile[0])
            self.__parent.settings.setValue("last_stationfile_directory", path)

    def saveStationsAs(self):
        inventory = self.__parent.get_inventory()
        if inventory is None:
            self.errorPopup('Oops... There are no stations to save')
            return

        if self.__parent.get_project() is None:
            # force a new filename...
            previousDirectory = self.__parent.settings.value("last_stationfile_directory", QDir.homePath())
        else:
            # There is an open project, so make the default save location correspond to what the project wants
            previousDirectory = str(self.__parent.get_project().get_stationsPath())

        # print('previousDirectory = {}'.format(str(previousDirectory)))
        self.__savefile = QFileDialog.getSaveFileName(self, 'Save StationXML File...', previousDirectory)
        # print('savefile = {}'.format(self.__savefile))
        if self.__savefile[0]:
            self.__parent._inv.write(self.__savefile[0], format='stationxml', validate=True)
            path = os.path.dirname(self.__savefile[0])
            self.__parent.settings.setValue("last_stationfile_directory", path)

    def loadStations(self):

        if self.__parent.get_project() is None:
            # force a new filename...
            previousDirectory = self.__parent.settings.value("last_stationfile_directory", QDir.homePath())
        else:
            # There is an open project, so make the default save location correspond to what the project wants
            previousDirectory = str(self.__parent.get_project().get_stationsPath())

        self.__openfile = QFileDialog.getOpenFileName(self, 'Open File', previousDirectory)

        if self.__openfile[0]:
            try:
                newinventory = read_inventory(self.__openfile[0], format='stationxml')
            except Exception:
                self.errorPopup("\nThis doesn't seem to be a valid XML file")
                return

            if self.__parent._inv is not None:
                self.__parent._inv += newinventory
            else:
                self.__parent._inv = newinventory

            self.setInventory(self.__parent._inv)

            self.inventory_changed.emit(self.__parent._inv)

    def get_current_center(self):
        # this method will calculate the center of the current inventory and will return a [lat,lon]

        # TODO: This is not really setup right now to handle the (very rare) case where an array straddles the
        # international date line
        inventory = self.__parent.get_inventory()

        lat, lon, ele, cnt = 0, 0, 0, 0

        for network in inventory:
            for station in network:
                lat += station.latitude
                lon += station.longitude
                ele += station.elevation
                cnt += 1

        return [lat / cnt, lon / cnt, ele / cnt]

    def reconcileStations(self):
        needed_stations = []
        loaded_stations = []
        trace_stations = []

        streams = self.__parent.get_streams()
        inventory = self.__parent.get_inventory()
        
        if streams is None:
            return  # Nothing to reconcile

        # populate a list of all the stations in the current stream
        for trace in streams:
            trace_split = trace.id.split('.')
            name = ''
            if trace_split[2] == '':
                name = trace_split[0] + '.' + trace_split[1]
            else:
                # There is a location code, so deal with it
                name = trace_split[0] + '.' + trace_split[1] + '.' + trace_split[2]

            if name not in trace_stations:
                trace_stations.append(name)

        if inventory is None:
            # No inventory loaded, so we need to get everything
            needed_stations = trace_stations
        else:
            # we already have inventory loaded, so we need to get the stations for waveforms that need it
            # First find all the loaded stations
            for network in inventory.networks:
                for station in network.stations:
                    name = ''
                    if len(station.channels) > 0:
                        for channel in station.channels:
                            name = network.code + '.' + station.code + '.' + channel.location_code
                    else:
                        name = network.code + '.' + station.code

                    if name not in loaded_stations:
                        loaded_stations.append(name)

            # now find all the stations that ARENT already loaded
            for sta in trace_stations:
                if sta not in loaded_stations:
                    needed_stations.append(sta)

        if needed_stations is not None:
            if self.matchDialog.exec_(needed_stations, (self.__parent.get_earliest_start_time(), self.__parent.get_earliest_start_time())):
                newInventory = self.matchDialog.getInventory()
                if newInventory is not None:
                    if inventory is None:
                        inventory = newInventory
                    else:
                        inventory += newInventory

                    self.__parent.set_inventory(inventory)

    def errorPopup(self, message):
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Information)
        msgBox.setText(message)
        msgBox.setWindowTitle("Oops...")
        msgBox.exec_()