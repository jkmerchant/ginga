# This is open-source software licensed under a BSD license.
# Please see the file LICENSE.txt for details.
#
import numpy as np

from ginga import cmap, imap, ColorDist
from ginga.RGBMap import RGBMapper
from ginga.gw import Widgets, ColorBar

from .base import Stage, StageAction


class RGBMap(Stage):

    _stagename = 'rgb-mapper'

    def __init__(self):
        super().__init__()

        self.rgbmap = None
        self.calg_names = ColorDist.get_dist_names()
        self.cmap_names = cmap.get_names()
        self.imap_names = imap.get_names()
        self.order = 'RGB'

        self._calg_name = 'linear'
        self._cmap_name = 'gray'
        self._imap_name = 'ramp'
        self._invert_cmap = False
        self._rotate_cmap_pct = 0.0
        self._contrast = 0.5
        self._brightness = 0.5

        self.viewer = None
        self.fv = None

    def build_gui(self, container):
        self.viewer = self.pipeline.get('viewer')
        self.fv = self.pipeline.get("fv")
        top = Widgets.VBox()

        # create and initialize RGB mapper
        # TODO: currently hash size cannot be changed
        self.rgbmap = RGBMapper(self.logger)
        self.rgbmap.get_settings().set(color_algorithm=self._calg_name,
                                       color_map=self._cmap_name,
                                       intensity_map=self._imap_name,
                                       color_map_invert=self._invert_cmap,
                                       color_map_rot_pct=self._rotate_cmap_pct,
                                       contrast=self._contrast,
                                       brightness=self._brightness)
        self.rgbmap.add_callback('changed', self.rgbmap_changed_cb)

        self.settings_keys = list(self.rgbmap.settings_keys)
        self.settings_keys.remove('color_hashsize')

        fr = Widgets.Frame("Color Distribution")

        captions = (('Algorithm:', 'label', 'Algorithm', 'combobox'),
                    #('Table Size:', 'label', 'Table Size', 'entryset'),
                    ('Dist Defaults', 'button'))

        w, b = Widgets.build_info(captions, orientation='vertical')
        self.w.update(b)
        self.w.calg_choice = b.algorithm
        #self.w.table_size = b.table_size
        b.algorithm.set_tooltip("Choose a color distribution algorithm")
        #b.table_size.set_tooltip("Set size of the distribution hash table")
        b.dist_defaults.set_tooltip("Restore color distribution defaults")
        b.dist_defaults.add_callback('activated',
                                     lambda w: self.set_default_distmaps())

        combobox = b.algorithm
        options = []
        for name in self.calg_names:
            options.append(name)
            combobox.append_text(name)
        try:
            index = self.calg_names.index(self._calg_name)
            combobox.set_index(index)
        except Exception:
            pass
        combobox.add_callback('activated', self.set_calg_cb)

        fr.set_widget(w)
        top.add_widget(fr, stretch=0)

        # COLOR MAPPING OPTIONS
        fr = Widgets.Frame("Color Mapping")

        captions = (('Colormap:', 'label', 'Colormap', 'combobox'),
                    ('Intensity:', 'label', 'Intensity', 'combobox'),
                    ('Rotate:', 'label', 'rotate_cmap', 'hscale'),
                    ('Invert CMap', 'checkbutton', 'Unrotate CMap', 'button'),
                    ('Color Defaults', 'button', 'Copy from viewer', 'button'))
        w, b = Widgets.build_info(captions, orientation='vertical')
        self.w.update(b)
        self.w.cmap_choice = b.colormap
        self.w.imap_choice = b.intensity

        b.invert_cmap.set_tooltip("Invert color map")
        b.invert_cmap.set_state(False)
        b.invert_cmap.add_callback('activated', self.invert_cmap_cb)

        b.rotate_cmap.set_tracking(False)
        b.rotate_cmap.set_limits(0, 100, incr_value=1)
        b.rotate_cmap.set_value(0)
        b.rotate_cmap.add_callback('value-changed', self.rotate_cmap_cb)
        b.rotate_cmap.set_tooltip("Rotate the colormap")

        b.colormap.set_tooltip("Choose a color map for this image")
        b.intensity.set_tooltip("Choose an intensity map for this image")
        b.unrotate_cmap.set_tooltip("Undo cmap rotation")
        b.unrotate_cmap.add_callback('activated', self.unrotate_cmap_cb)
        b.color_defaults.set_tooltip("Restore all color map settings to defaults")
        b.color_defaults.add_callback('activated',
                                      lambda w: self.set_default_cmaps())
        fr.set_widget(w)

        combobox = b.colormap
        options = []
        for name in self.cmap_names:
            options.append(name)
            combobox.append_text(name)
        try:
            index = self.cmap_names.index(self._cmap_name)
        except Exception:
            index = self.cmap_names.index('gray')
        combobox.set_index(index)
        combobox.add_callback('activated', self.set_cmap_cb)

        combobox = b.intensity
        options = []
        for name in self.imap_names:
            options.append(name)
            combobox.append_text(name)
        try:
            index = self.imap_names.index(self._imap_name)
        except Exception:
            index = self.imap_names.index('ramp')
        combobox.set_index(index)
        combobox.add_callback('activated', self.set_imap_cb)

        b.copy_from_viewer.set_tooltip("Copy settings from viewer")
        b.copy_from_viewer.add_callback('activated', self.copy_from_viewer_cb)

        top.add_widget(fr, stretch=0)

        # CONTRAST MANIPULATIONS
        fr = Widgets.Frame("Contrast and Brightness (Bias)")

        captions = (('Contrast:', 'label', 'contrast', 'hscale'),
                    ('Brightness:', 'label', 'brightness', 'hscale'),
                    ('_cb1', 'spacer', '_hbox_cb', 'hbox'))
        w, b = Widgets.build_info(captions, orientation='vertical')
        self.w.update(b)

        b.contrast.set_tracking(False)
        b.contrast.set_limits(0, 100, incr_value=1)
        b.contrast.set_value(50)
        b.contrast.add_callback('value-changed', self.contrast_set_cb)
        b.contrast.set_tooltip("Set contrast for the viewer")

        b.brightness.set_tracking(False)
        b.brightness.set_limits(0, 100, incr_value=1)
        b.brightness.set_value(50)
        b.brightness.add_callback('value-changed', self.brightness_set_cb)
        b.brightness.set_tooltip("Set brightness/bias for the viewer")

        btn = Widgets.Button('Default Contrast')
        btn.set_tooltip("Reset contrast to default")
        btn.add_callback('activated', self.restore_contrast_cb)
        b._hbox_cb.add_widget(btn, stretch=0)
        btn = Widgets.Button('Default Brightness')
        btn.set_tooltip("Reset brightness to default")
        btn.add_callback('activated', self.restore_brightness_cb)
        b._hbox_cb.add_widget(btn, stretch=0)

        fr.set_widget(w)
        top.add_widget(fr, stretch=0)

        # add colorbar
        fr = Widgets.Frame("Color Map")
        height = 50
        settings = self.rgbmap.get_settings()
        settings.set(cbar_height=height, fontsize=10)
        cbar = ColorBar.ColorBar(self.logger, rgbmap=self.rgbmap,
                                 link=True,
                                 settings=settings)
        vmax = self.rgbmap.get_hash_size() - 1
        cbar.cbar_view.cut_levels(0, vmax)
        cbar_w = cbar.get_widget()
        cbar_w.resize(-1, height)

        self.colorbar = cbar
        #cbar.add_callback('motion', self.cbar_value_cb)

        top.add_widget(cbar_w, stretch=0)

        container.set_widget(top)

    @property
    def calg_name(self):
        return self._calg_name

    @calg_name.setter
    def calg_name(self, val):
        self._calg_name = val
        if self.gui_up:
            idx = self.calg_names.index(val)
            self.w.algorithm.set_index(idx)
            self.rgbmap.set_color_algorithm(val)

    @property
    def cmap_name(self):
        return self._cmap_name

    @cmap_name.setter
    def cmap_name(self, val):
        self._cmap_name = val
        if self.gui_up:
            idx = self.cmap_names.index(val)
            self.w.colormap.set_index(idx)
            self.rgbmap.set_color_map(val)

    @property
    def imap_name(self):
        return self._imap_name

    @imap_name.setter
    def imap_name(self, val):
        self._imap_name = val
        if self.gui_up:
            idx = self.imap_names.index(val)
            self.w.intensity.set_index(idx)
            self.rgbmap.set_intensity_map(val)

    @property
    def invert_cmap(self):
        return self._invert_cmap

    @invert_cmap.setter
    def invert_cmap(self, tf):
        self._invert_cmap = tf
        if self.gui_up:
            self.w.invert_cmap.set_state(tf)
            self.rgbmap.get_settings().set(color_map_invert=tf)

    @property
    def rotate_cmap(self):
        return self._rotate_cmap_pct

    @rotate_cmap.setter
    def rotate_cmap(self, pct):
        self._rotate_cmap_pct = pct
        if self.gui_up:
            self.w.rotate_cmap.set_value(int(pct * 100.0))
            self.rgbmap.get_settings().set(color_map_rot_pct=pct)

    @property
    def contrast(self):
        return self._contrast

    @contrast.setter
    def contrast(self, pct):
        self._contrast = pct
        if self.gui_up:
            self.w.contrast.set_value(int(pct * 100))
            self.rgbmap.get_settings().set(contrast=pct)

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, pct):
        self._brightness = pct
        if self.gui_up:
            self.w.brightness.set_value(int(pct * 100))
            self.rgbmap.get_settings().set(brightness=pct)

    def set_cmap_cb(self, w, index):
        """This callback is invoked when the user selects a new color
        map from the UI."""
        old_cmap_name = self._cmap_name
        name = cmap.get_names()[index]
        self.cmap_name = name
        self.pipeline.push(StageAction(self,
                                       dict(cmap_name=old_cmap_name),
                                       dict(cmap_name=self._cmap_name),
                                       descr="rgbmap / change cmap"))

        self.pipeline.run_from(self)

    def set_imap_cb(self, w, index):
        """This callback is invoked when the user selects a new intensity
        map from the preferences pane."""
        old_imap_name = self._imap_name
        name = imap.get_names()[index]
        self.imap_name = name
        self.pipeline.push(StageAction(self,
                                       dict(imap_name=old_imap_name),
                                       dict(imap_name=self._imap_name),
                                       descr="rgbmap / change imap"))

        self.pipeline.run_from(self)

    def set_calg_cb(self, w, index):
        """This callback is invoked when the user selects a new color
        hashing algorithm from the UI."""
        old_calg_name = self._calg_name
        name = self.calg_names[index]
        self.calg_name = name
        self.pipeline.push(StageAction(self,
                                       dict(calg_name=old_calg_name),
                                       dict(calg_name=self._calg_name),
                                       descr="rgbmap / change calg"))

        self.pipeline.run_from(self)

    def rotate_cmap_cb(self, w, val):
        old_val = self._rotate_cmap_pct
        pct = val / 100.0
        self.rotate_cmap = pct
        self.pipeline.push(StageAction(self,
                                       dict(rotate_cmap=old_val),
                                       dict(rotate_cmap=self._rotate_cmap_pct),
                                       descr=f"rgbmap / rotate cmap: {pct}"))

        self.pipeline.run_from(self)

    def invert_cmap_cb(self, w, tf):
        old_val = self._invert_cmap
        self.invert_cmap = tf
        self.pipeline.push(StageAction(self,
                                       dict(invert_cmap=old_val),
                                       dict(invert_cmap=self._invert_cmap),
                                       descr=f"rgbmap / invert cmap {tf}"))

        self.pipeline.run_from(self)

    def unrotate_cmap_cb(self, w):
        self.rotate_cmap_cb(w, 0)

    def set_default_cmaps(self):
        old = dict(cmap_name=self._cmap_name, imap_name=self._imap_name)
        cmap_name = "gray"
        imap_name = "ramp"
        new = dict(cmap_name=cmap_name, imap_name=imap_name)
        self.pipeline.push(StageAction(self, old, new,
                                       descr="rgbmap / change cmap,imap"))
        self.cmap_name = cmap_name
        self.imap_name = imap_name

        self.pipeline.run_from(self)

    def contrast_set_cb(self, w, val):
        old_val = self._contrast
        pct = val / 100.0
        self.contrast = pct
        self.pipeline.push(StageAction(self,
                                       dict(contrast=old_val),
                                       dict(contrast=self._contrast),
                                       descr=f"rgbmap / contrast: {pct}"))

        self.pipeline.run_from(self)

    def brightness_set_cb(self, w, val):
        old_val = self._brightness
        pct = val / 100.0
        self.brightness = pct
        self.pipeline.push(StageAction(self,
                                       dict(brightness=old_val),
                                       dict(brightness=self._brightness),
                                       descr=f"rgbmap / brightness: {pct}"))

        self.pipeline.run_from(self)

    def restore_contrast_cb(self, w):
        self.contrast_set_cb(w, 50)

    def restore_brightness_cb(self, w):
        self.brightness_set_cb(w, 50)

    def set_default_distmaps(self):
        old = dict(calg_name=self._calg_name)
        name = 'linear'
        new = dict(calg_name=name)
        self.pipeline.push(StageAction(self, old, new,
                                       descr="rgbmap / change calg"))
        self.calg_name = name

        self.pipeline.run_from(self)

    def copy_from_viewer_cb(self, w):
        rgbmap = self.viewer.get_rgbmap()
        rgbmap.copy_attributes(self.rgbmap, keylist=self.settings_keys)

        self.pipeline.run_from(self)

    def rgbmap_changed_cb(self, rgbmap):
        self.fv.gui_do_oneshot('pl-rgbmap', self.pipeline.run_from, self)

    def run(self, prev_stage):
        data = self.pipeline.get_data(prev_stage)
        self.verify_2d(data)

        if self._bypass or data is None:
            self.pipeline.send(res_np=data)
            return

        if not np.issubdtype(data.dtype, np.uint):
            data = data.astype(np.uint)

        # get RGB mapped array
        res_np = self.rgbmap.get_rgb_array(data, order=self.order)

        self.pipeline.send(res_np=res_np)

    def __str__(self):
        return self._stagename

    def _get_state(self):
        return dict(calg_name=self._calg_name, cmap_name=self._cmap_name,
                    imap_name=self._imap_name)

    def export_as_dict(self):
        d = super().export_as_dict()
        d.update(self._get_state())
        return d

    def import_from_dict(self, d):
        super().import_from_dict(d)
        self.calg_name = d['calg_name']
        self.cmap_name = d['cmap_name']
        self.imap_name = d['imap_name']
