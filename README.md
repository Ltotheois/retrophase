# I(t) to I(f)

This package provides an graphical user interface to convert a timesignel (I(t)) to a frequency spectrum (I(f)) via Fast Fourier transform (FFT).
Different window functions can be applied, the window position and duration can be changed interactively and zeropadding can be applied.

The default options are chosen to fit our usecase in the [Labastro Group Cologne](https://astro.uni-koeln.de/schlemmer).
If your dataformats are different, please modify the default options file accordingly.
To do this, start the program and save the default values via *File > Save as default*. This creates the file "~/.itif./default.json".

This file is in simple json format and can be edited with your editor of choice.

Find the project on [PyPi](https://pypi.org/project/ItIf/) or install via
```
pip install itif
```