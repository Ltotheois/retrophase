#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Author: Luis Bonah
# Description: Program to retrospectively change the phase of absorption measurements that are demodulated with a lock-in amplifier.


import os
import sys
import json
import glob
import argparse
import traceback as tb
import numpy as np
import pandas as pd
import threading
import matplotlib
from matplotlib import gridspec, figure
from matplotlib.backends.backend_qtagg import FigureCanvas, NavigationToolbar2QT

from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import *

QLocale.setDefault(QLocale("en_EN"))

homefolder = os.path.join(os.path.expanduser("~"), ".retro")
if not os.path.isdir(homefolder):
	os.mkdir(homefolder)

OPTIONFILE = os.path.join(homefolder, "default.json")
PYQT_MAX = 2147483647

matplotlib.rcParams['axes.formatter.useoffset'] = False
matplotlib.rcParams['patch.facecolor'] = "blue"

def change_phase(fs, xs, ys, phase_in_degree):
	phase_in_radian = phase_in_degree / 180 * np.pi
	rs = (xs + 1j * ys)
	zs = np.real(rs * np.exp(-1j * phase_in_radian))
	return(zs)

def autophase(fs, xs, ys, step=4, target_resolution=0.1):
	phase_min = 0
	phase_max = 360
	
	while True:
		phases_to_test = np.arange(phase_min, phase_max + step, step)
		best_phase = autophase_core(fs, xs, ys, phases_to_test)
		
		if step < target_resolution:
			break
		
		phase_min = best_phase - 2 * step
		phase_max = best_phase + 2 * step
		step = step / 10
	
	return(best_phase)
	
def autophase_core(fs, xs, ys, phases_to_test):
	max_per_phase = [change_phase(fs, xs, ys, phase).max() for phase in phases_to_test]
	best_phase = phases_to_test[np.argmax(max_per_phase)]
	return(best_phase)

### GUI
class QSpinBox(QSpinBox):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.setRange(0, PYQT_MAX)
		
	def setRange(self, min, max):
		min = min if not min is None else -np.inf
		max = max if not max is None else +np.inf
		return super().setRange(min, max)

class QDoubleSpinBox(QDoubleSpinBox):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.setDecimals(20)
		self.setRange(0, PYQT_MAX)
		
		try:
			self.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
		except:
			pass

	def textFromValue(self, value):
		return(f"{value:.10f}".rstrip("0").rstrip("."))

	def valueFromText(self, text):
		return(np.float64(text))

	def setRange(self, min, max):
		min = min if not min is None else -np.inf
		max = max if not max is None else +np.inf
		return super().setRange(min, max)



class MainWindow(QMainWindow):
	updateconfig = pyqtSignal(tuple)
	redrawplot = pyqtSignal()
	
	def __init__(self, parent=None, **kwargs):
		global config
		
		super().__init__(parent)
		self.setAcceptDrops(True)
		self.timer = None
		self.update_data_thread = None
		self.update_data_lock = threading.RLock()
		
		self.data = None
		self.files = None
		self.fileindex = None

		config = self.config = Config(self.updateconfig, {
			"mpltoolbar": True,
			"savefigure_kwargs": {
				"dpi": 600,
			},
	
			"asksavename": False,
			"savefile_kwargs": {
				"delimiter": "\t",
			},
			
			"show_y": True,
			"phase": 0,
			"rescale": True,
			"margin": 0.1,
			"rescale": True,
			"autophase_step": kwargs['step'],
			"autophase_targetresolution": kwargs['resolution'],
		})

		self.gui()
		self.setWindowTitle("RETRO")
		self.readoptions(OPTIONFILE, ignore=True)
		
		files = kwargs.get('files')
		if files:
			self.open_files(files)
		
		self.show()

	def dragEnterEvent(self, event):
		if event.mimeData().hasUrls():
			event.accept()
		else:
			event.ignore()

	def dropEvent(self, event):
		files = [url.toLocalFile() for url in event.mimeData().urls()]
		self.open_files(files)

	def gui_menu(self):
		filemenu = self.menuBar().addMenu(f"File")

		filemenu.addAction(QQ(QAction, parent=self, text="&Open Files", shortcut="Ctrl+O", tooltip="Open a new file", change=lambda x: self.open_files()))
		filemenu.addAction(QQ(QAction, parent=self, text="&Save File", shortcut="Ctrl+S", tooltip="Save data to file", change=lambda x: self.save_file()))
		filemenu.addSeparator()
		filemenu.addAction(QQ(QAction, parent=self, text="&Load Options", tooltip="Load option file", change=lambda x: self.readoptions()))
		filemenu.addAction(QQ(QAction, parent=self, text="&Save Options", tooltip="Save options to file", change=lambda x: self.saveoptions()))
		filemenu.addSeparator()
		filemenu.addAction(QQ(QAction, parent=self, text="&Save as default", tooltip="Save options as default options", change=lambda x: self.saveoptions(OPTIONFILE)))

		actionmenu = self.menuBar().addMenu(f"Actions")
		actionmenu.addAction(QQ(QAction, "mpltoolbar", parent=self, text="&Show MPL Toolbar", tooltip="Show or hide matplotlib toolbar", checkable=True))
		actionmenu.addSeparator()
		actionmenu.addAction(QQ(QAction, "rescale", parent=self, text="&Rescale Plot", tooltip="Rescale plot when updating", checkable=True))
		actionmenu.addSeparator()
		actionmenu.addAction(QQ(QAction, "show_y", parent=self, text="&Show Y Component", tooltip="Show or hide the y component", checkable=True))
		actionmenu.addSeparator()
		actionmenu.addAction(QQ(QAction, parent=self, text="&Save Figure", tooltip="Save the figure", change=lambda x: self.savefigure()))

	def gui(self):
		self.gui_menu()
	
		layout = QVBoxLayout()

		self.fig = figure.Figure()
		gs = gridspec.GridSpec(2, 1, hspace=0, wspace=0)
		self.plotcanvas = FigureCanvas(self.fig)
		self.plotcanvas.setMinimumHeight(200)
		self.plotcanvas.setMinimumWidth(200)
		layout.addWidget(self.plotcanvas)
		
		self.config.register(["phase", ], self.update_data)
		
		self.redrawplot.connect(self.fig.canvas.draw_idle)

		self.ax0 = self.fig.add_subplot(gs[0, :])
		self.ax1 = self.fig.add_subplot(gs[1, :], sharex=self.ax0)

		self.X_line = self.ax0.plot([], [], color="#0336FF", label="X")[0]
		self.Y_line = self.ax0.plot([], [], color="#FF0266", label="Y")[0]
		self.Z_line = self.ax1.plot([], [], color="#fbd206", label="Z")[0]
		
		self.ax0.get_xaxis().set_visible(False)
		self.ax0.legend()
		self.ax1.legend()

		self.mpltoolbar = NavigationToolbar2QT(self.plotcanvas, self)
		self.mpltoolbar.setVisible(self.config["mpltoolbar"])
		self.config.register("mpltoolbar", lambda: self.mpltoolbar.setVisible(self.config["mpltoolbar"]))
		self.addToolBar(self.mpltoolbar)

		self.notificationarea = QLabel()
		self.notificationarea.setWordWrap(True)
		self.notificationarea.setHidden(True)
		layout.addWidget(self.notificationarea)

		button_layout = QGridLayout()
		
		row_index = 0
		column_index = 0
		
		button_layout.addWidget(QLabel("Phase [Degree]: "), row_index, column_index)
		button_layout.addWidget(QQ(QDoubleSpinBox, "phase", range=(0, 360), singlestep=1), row_index, column_index+1)

		row_index += 1
		column_index =0 
		
		button_layout.addWidget(QQ(QPushButton, text="Auto Phase", change=lambda: self.autophase_gui()), row_index, column_index)
		column_index += 1
		button_layout.addWidget(QQ(QPushButton, text="Load", change=lambda: self.open_files()), row_index, column_index)
		column_index += 1
		button_layout.addWidget(QQ(QPushButton, text="Apply all", change=lambda: self.apply_all()), row_index, column_index)
		
		row_index += 1
		column_index = 0
		
		button_layout.addWidget(QQ(QPushButton, text="Previous", change=lambda: self.update_selected_file(self.fileindex-1)), row_index, column_index)
		column_index += 1
		button_layout.addWidget(QQ(QPushButton, text="Save", change=lambda: self.save_file()), row_index, column_index)
		column_index += 1
		button_layout.addWidget(QQ(QPushButton, text="Next", change=lambda: self.update_selected_file(self.fileindex+1)), row_index, column_index)
		
		
		layout.addLayout(button_layout)
		widget = QWidget()
		self.setCentralWidget(widget)
		widget.setLayout(layout)

	def open_files(self, fnames=None):
		if not fnames:
			fnames, _ = QFileDialog.getOpenFileNames(None, 'Choose Files to open',"")
		if not fnames:
			self.notification("No files were selected. Keeping current data.")
			return
		
		self.files = fnames
		self.update_selected_file()

		
	def save_file(self):
		fname = self.files[self.fileindex]
		if fname is None:
			self.notification("No file selected.")
			return
		
		if self.config["asksavename"]:
			savename, _ = QFileDialog.getSaveFileName(None, 'Choose File to Save to',"")
		else:
			basename, extension = os.path.splitext(fname)
			savename = basename + '.datpopt'
		
		if not savename:
			self.notification("No filename specified for saving.")
			return

		fs, xs, ys = self.data
		zs = change_phase(fs, xs, ys, self.config["phase"])
		data = np.vstack((fs, zs)).T
		
		np.savetxt(savename, data, **self.config["savefile_kwargs"])
		self.notification(f"Saved data successfully to '{savename}'")

	def notification(self, text):
		self.notificationarea.setText(text)
		self.notificationarea.setHidden(False)

		if self.timer:
			self.timer.stop()
		self.timer = QTimer(self)
		self.timer.setSingleShot(True)
		self.timer.timeout.connect(lambda: self.notificationarea.setHidden(True))
		self.timer.start(5000)

	def saveoptions(self, filename=None):
		if filename is None:
			filename, _ = QFileDialog.getSaveFileName(self, "Save options to file")
			if not filename:
				return

		with open(filename, "w+") as optionfile:
			json.dump(self.config, optionfile, indent=2)
		self.notification("Options have been saved")

	def readoptions(self, filename=None, ignore=False):
		if filename is None:
			filename, _ = QFileDialog.getOpenFileName(self, "Read options from file")
			if not filename:
				return

		if not os.path.isfile(filename):
			if not ignore:
				self.notification(f"Option file '{filename}' does not exist.")
			return

		with open(filename, "r") as optionfile:
			values = json.load(optionfile)
		for key, value in values.items():
			self.config[key] = value
		self.notification("Options have been loaded")


	def savefigure(self):
		fname, _ = QFileDialog.getSaveFileName(None, 'Choose File to Save to',"")
		if not fname:
			return
		
		self.fig.savefig(fname, **config["savefigure_kwargs"])

	def update_selected_file(self, index=0):
		index = max(0, index)
		index = min(len(self.files)-1, index)
		self.fileindex = index
		fname = self.files[self.fileindex]
		
		fs, xs, ys = np.genfromtxt(fname, delimiter='\t', unpack=True)
		self.data = fs, xs, ys
		
		self.update_data(force_rescale=True)
		self.notification(f"File {index+1} out of {len(self.files)} currently selected. Name is {fname}.")

	def autophase_gui(self):
		if not self.data:
			self.notification("No data loaded")
			return
		
		fs, xs, ys = self.data
		step = config['autophase_step']
		target_res = config['autophase_targetresolution']
		best_phase = autophase(fs, xs, ys, step=step, target_resolution=target_res)
		
		self.config["phase"] = best_phase

	def apply_all(self):
		phase = self.config["phase"]
		for fname in self.files:
			fs, xs, ys = np.genfromtxt(fname, delimiter='\t', unpack=True)
			zs = change_phase(fs, xs, ys, phase)

			basename, extension = os.path.splitext(fname)
			savename = basename + "RETRO" + extension
			
			data = np.vstack((fs, zs)).T
			np.savetxt(savename, data, **self.config["savefile_kwargs"])
		
		self.notification(f"Applied the current phase of {phase} deg to all files.")


	def update_data(self, force_rescale=False):
		thread = threading.Thread(target=self.update_data_core, args=(force_rescale, ))
		with self.update_data_lock:
			thread.start()
			self.update_data_thread = thread.ident
		return(thread)

	def update_data_core(self, force_rescale):
		with self.update_data_lock:
			ownid = threading.current_thread().ident
		
		try:
			if self.data is None:
				return
			breakpoint(ownid, self.update_data_thread)
			
			fs, xs, ys = self.data
			zs = change_phase(fs, xs, ys, config["phase"])
			
			breakpoint(ownid, self.update_data_thread)
			
			self.X_line.set_data(fs, xs)
			self.Z_line.set_data(fs, zs)
			
			if self.config["show_y"]:
				self.Y_line.set_data(fs, ys)
			else:
				self.Y_line.set_data([], [])
				
				
			
			breakpoint(ownid, self.update_data_thread)
			
			if force_rescale or self.config["rescale"]:
				# x-ranges are coupled -> only set on one axis
				self.ax0.set_xlim(fs.min(), fs.max())
				
				if self.config["show_y"]:
					ymin, ymax = min(xs.min(), ys.min()), max(xs.max(), ys.max())
				else:
					ymin, ymax = xs.min(), xs.max()
				
				ydiff = ymax - ymin
				ymin, ymax = ymin - ydiff * self.config["margin"], ymax + ydiff * self.config["margin"]
				self.ax0.set_ylim(ymin, ymax)
				
				ymin, ymax = zs.min(), zs.max()
				ydiff = ymax - ymin
				ymin, ymax = ymin - ydiff * self.config["margin"], ymax + ydiff * self.config["margin"]
				self.ax1.set_ylim(ymin, ymax)
			
			self.redrawplot.emit()
		except BreakpointError as E:
			pass

class Config(dict):
	def __init__(self, signal, init_values={}):
		super().__init__(init_values)
		self.signal = signal
		self.signal.connect(self.callback)
		self.callbacks = pd.DataFrame(columns=["id", "key", "widget", "function"], dtype="object").astype({"id": np.uint})

	def __setitem__(self, key, value, widget=None):
		super().__setitem__(key, value)
		self.signal.emit((key, value, widget))

	def callback(self, args):
		key, value, widget = args
		if widget:
			callbacks_widget = self.callbacks.query(f"key == @key and widget != @widget")
		else:
			callbacks_widget = self.callbacks.query(f"key == @key")
		for i, row in callbacks_widget.iterrows():
			row["function"]()

	def register(self, keys, function):
		if not isinstance(keys, (tuple, list)):
			keys = [keys]
		for key in keys:
			id = 0
			df = self.callbacks
			df.loc[len(df), ["id", "key", "function"]] = id, key, function

	def register_widget(self, key, widget, function):
		ids = set(self.callbacks["id"])
		id = 1
		while id in ids:
			id += 1
		df = self.callbacks
		df.loc[len(df), ["id", "key", "function", "widget"]] = id, key, function, widget
		widget.destroyed.connect(lambda x, id=id: self.unregister_widget(id))

	def unregister_widget(self, id):
		self.callbacks.drop(self.callbacks[self.callbacks["id"] == id].index, inplace=True)

def QQ(widgetclass, config_key=None, **kwargs):
	widget = widgetclass()

	if "range" in kwargs:
		widget.setRange(*kwargs["range"])
	if "maxWidth" in kwargs:
		widget.setMaximumWidth(kwargs["maxWidth"])
	if "maxHeight" in kwargs:
		widget.setMaximumHeight(kwargs["maxHeight"])
	if "minWidth" in kwargs:
		widget.setMinimumWidth(kwargs["minWidth"])
	if "minHeight" in kwargs:
		widget.setMinimumHeight(kwargs["minHeight"])
	if "color" in kwargs:
		widget.setColor(kwargs["color"])
	if "text" in kwargs:
		widget.setText(kwargs["text"])
	if "options" in kwargs:
		options = kwargs["options"]
		if isinstance(options, dict):
			for key, value in options.items():
				widget.addItem(key, value)
		else:
			for option in kwargs["options"]:
				widget.addItem(option)
	if "width" in kwargs:
		widget.setFixedWidth(kwargs["width"])
	if "tooltip" in kwargs:
		widget.setToolTip(kwargs["tooltip"])
	if "placeholder" in kwargs:
		widget.setPlaceholderText(kwargs["placeholder"])
	if "singlestep" in kwargs:
		widget.setSingleStep(kwargs["singlestep"])
	if "wordwrap" in kwargs:
		widget.setWordWrap(kwargs["wordwrap"])
	if "align" in kwargs:
		widget.setAlignment(kwargs["align"])
	if "rowCount" in kwargs:
		widget.setRowCount(kwargs["rowCount"])
	if "columnCount" in kwargs:
		widget.setColumnCount(kwargs["columnCount"])
	if "move" in kwargs:
		widget.move(*kwargs["move"])
	if "default" in kwargs:
		widget.setDefault(kwargs["default"])
	if "textFormat" in kwargs:
		widget.setTextFormat(kwargs["textFormat"])
	if "checkable" in kwargs:
		widget.setCheckable(kwargs["checkable"])
	if "shortcut" in kwargs:
		widget.setShortcut(kwargs["shortcut"])
	if "parent" in kwargs:
		widget.setParent(kwargs["parent"])
	if "completer" in kwargs:
		widget.setCompleter(kwargs["completer"])
	if "hidden" in kwargs:
		widget.setHidden(kwargs["hidden"])
	if "visible" in kwargs:
		widget.setVisible(kwargs["visible"])
	if "stylesheet" in kwargs:
		widget.setStyleSheet(kwargs["stylesheet"])
	if "enabled" in kwargs:
		widget.setEnabled(kwargs["enabled"])
	if "items" in kwargs:
		for item in kwargs["items"]:
			widget.addItem(item)
	if "readonly" in kwargs:
		widget.setReadOnly(kwargs["readonly"])
	if "prefix" in kwargs:
		widget.setPrefix(kwargs["prefix"])

	if widgetclass in [QSpinBox, QDoubleSpinBox]:
		setter = widget.setValue
		changer = widget.valueChanged.connect
		getter = widget.value
	elif widgetclass == QCheckBox:
		setter = widget.setChecked
		changer = widget.stateChanged.connect
		getter = widget.isChecked
	elif widgetclass == QPlainTextEdit:
		setter = widget.setPlainText
		changer = widget.textChanged.connect
		getter = widget.toPlainText
	elif widgetclass == QLineEdit:
		setter = widget.setText
		changer = widget.textChanged.connect
		getter = widget.text
	elif widgetclass == QAction:
		setter = widget.setChecked
		changer = widget.triggered.connect
		getter = widget.isChecked
	elif widgetclass == QPushButton:
		setter = widget.setDefault
		changer = widget.clicked.connect
		getter = widget.isDefault
	elif widgetclass == QToolButton:
		setter = widget.setChecked
		changer = widget.clicked.connect
		getter = widget.isChecked
	elif widgetclass == QComboBox:
		setter = widget.setCurrentText
		changer = widget.currentTextChanged.connect
		getter = widget.currentText
	else:
		return widget

	if "value" in kwargs:
		setter(kwargs["value"])
	if config_key:
		setter(config[config_key])
		changer(lambda x=None, key=config_key: config.__setitem__(key, getter(), widget))
		config.register_widget(config_key, widget, lambda: setter(config[config_key]))
	if "change" in kwargs:
		changer(kwargs["change"])
	if "changes" in kwargs:
		for change in kwargs["changes"]:
			changer(change)

	return widget

class BreakpointError(Exception):
	pass

def breakpoint(ownid, lastid):
	if ownid != lastid:
		raise BreakpointError()

def except_hook(cls, exception, traceback):
	sys.__excepthook__(cls, exception, traceback)
	window.notification(f"{exception}\n{''.join(tb.format_tb(traceback))}")


def start_gui(kwargs):
	sys.excepthook = except_hook
	app = QApplication(sys.argv)
	window = MainWindow(**kwargs)
	sys.exit(app.exec())

def start_headless(kwargs):
	files = kwargs.get('files')
	if not files:
		print('No files were selected!')
		return
	
	step = kwargs['step']
	res = kwargs['resolution']
	
	for file in files:
		fs, xs, ys = np.genfromtxt(file, delimiter='\t', unpack=True)
		best_phase = autophase(fs, xs, ys, step=step, target_resolution=res)
		
		basename, extension = os.path.splitext(file)
		savename = basename + '.datpopt'
		zs = change_phase(fs, xs, ys, best_phase)
		data = np.vstack((fs, zs)).T
		np.savetxt(savename, data, delimiter='\t')
		
		if best_phase < 0:
			best_phase += 360
		print(f'Optimal phase of {best_phase:-6.2f}° for file \'{file}\'')

def start():
	epilog = 'Program to retrospectively change the phase of absorption measurements that are demodulated with a lock-in amplifier.'
	parser = argparse.ArgumentParser(prog='Retrophase', epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
	
	parser.add_argument('files', nargs='*', type=str, help='Glob string for files to be loaded')
	parser.add_argument('--auto', '-a', action='store_true', help='Automatically determine the best phase for each file (will not start any gui)')
	parser.add_argument('--resolution', '-r', type=float, default=0.1, help='Specifies the target resolution for the autophase algorithm')
	parser.add_argument('--step', '-s', type=float, default=4, help='Specifies the initial step width for the autophase alogrithm')

	args = parser.parse_args()
	
	kwargs = {}
	
	if args.files:
		files = [ file for glob_str in args.files for file in glob.glob(glob_str, recursive=True) ]
		kwargs['files'] = files
	else:
		kwargs['files'] = []
	
	kwargs['resolution'] = args.resolution
	kwargs['step'] = args.step
	
	if args.auto:
		start_headless(kwargs)
	else:
		start_gui(kwargs)

if __name__ == '__main__':
	start()
