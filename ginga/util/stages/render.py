# This is open-source software licensed under a BSD license.
# Please see the file LICENSE.txt for details.
#
"""
These pipeline stages are used in creating the StandardPipelineRenderer,
the default renderer for standard widget backends.

[createbg] => [overlays] => [iccprof] => [flipswap] => [rotate] => [output]

"""
import numpy as np

from ginga import trcalc, RGBImage

from .base import Stage, StageError


class CreateBg(Stage):
    """Create the background RGB image, sized to fit the area that needs to
    be painted in the viewer, and big enough so there is room to rotate it.
    """

    _stagename = 'viewer-createbg'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer
        self.dtype = np.uint8

    def run(self, prev_stage):
        if prev_stage is not None:
            raise StageError("'{}' in wrong location".format(self._stagename))

        if self._bypass:
            self.pipeline.send(res_np=None)
            return

        state = self.pipeline.get('state')
        win_wd, win_ht = state.win_dim

        # calc minimum size of pixel image we will generate
        # necessary to fit the window in the desired size

        # Make a square from the scaled cutout, with room to rotate
        slop = 20
        side = int(np.sqrt(win_wd**2 + win_ht**2) + slop)
        wd = ht = side

        # Find center of new array
        ncx, ncy = wd // 2, ht // 2
        depth = len(state.order)

        # make backing image with the background color
        r, g, b = self.viewer.get_bg()
        res_np = trcalc.make_filled_array((ht, wd, depth), self.dtype,
                                          state.order, r, g, b, 1.0)

        self.pipeline.set(org_dim=(wd, ht), org_off=(ncx, ncy))
        self.pipeline.send(res_np=res_np)


class ICCProf(Stage):
    """Convert the given RGB data from the input ICC profile to the
    output ICC profile registered for the viewer.
    """
    _stagename = 'viewer-icc-profiler'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        data = self.pipeline.get_data(prev_stage)
        self.verify_2d(data)

        from ginga.util import rgb_cms

        working_profile = rgb_cms.working_profile
        t_ = self.viewer.get_settings()
        output_profile = t_.get('icc_output_profile', None)

        if (self._bypass or not rgb_cms.have_cms or
            None in [working_profile, output_profile]):
            self.pipeline.set(icc_output_profile=working_profile)
            self.pipeline.send(res_np=data)
            return

        # get rest of necessary conversion parameters
        to_intent = t_.get('icc_output_intent', 'perceptual')
        proofprof_name = t_.get('icc_proof_profile', None)
        proof_intent = t_.get('icc_proof_intent', 'perceptual')
        use_black_pt = t_.get('icc_black_point_compensation', False)
        try:
            data = rgb_cms.convert_profile_fromto(data,
                                                  working_profile,
                                                  output_profile,
                                                  to_intent=to_intent,
                                                  proof_name=proofprof_name,
                                                  proof_intent=proof_intent,
                                                  use_black_pt=use_black_pt,
                                                  logger=self.logger)

            self.logger.debug("Converted from '%s' to '%s' profile" % (
                working_profile, output_profile))

        except Exception as e:
            self.logger.warning("Error converting output from working profile: %s" % (str(e)))
            # TODO: maybe should have a traceback here
            self.logger.info("Output left unprofiled")

        self.pipeline.set(icc_output_profile=output_profile)
        self.pipeline.send(res_np=data)


class FlipSwap(Stage):
    """Flip or swap axes according the viewer settings.
    """

    _stagename = 'viewer-flipswap'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        data = self.pipeline.get_data(prev_stage)
        self.verify_2d(data)

        xoff, yoff = self.pipeline.get('org_off')
        if not self._bypass:
            flip_x, flip_y, swap_xy = self.viewer.get_transforms()

            ht, wd = data.shape[:2]

            # Do transforms as necessary
            data = trcalc.transform(data, flip_x=flip_x, flip_y=flip_y,
                                    swap_xy=swap_xy)
            if flip_y:
                yoff = ht - yoff
            if flip_x:
                xoff = wd - xoff
            if swap_xy:
                xoff, yoff = yoff, xoff

        self.pipeline.set(off=(xoff, yoff))
        self.pipeline.send(res_np=data)


class Rotate(Stage):
    """Rotate the image according the viewer settings.
    """

    _stagename = 'viewer-rotate'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        data = self.pipeline.get_data(prev_stage)
        self.verify_2d(data)

        if not self._bypass:
            rot_deg = self.viewer.get_rotation()

            if not np.isclose(rot_deg, 0.0):
                data = np.copy(data)
                #data = np.ascontiguousarray(data)
                data = trcalc.rotate_clip(data, -rot_deg, out=data,
                                          logger=self.logger)

            # apply other transforms
            if self.viewer._invert_y:
                # Flip Y for natural Y-axis inversion between FITS coords
                # and screen coords
                data = np.flipud(data)

        # dimensions may have changed in transformations
        ht, wd = data.shape[:2]
        xoff, yoff = self.pipeline.get('off')
        state = self.pipeline.get('state')
        ctr_x, ctr_y = state.ctr

        dst_x, dst_y = ctr_x - xoff, ctr_y - (ht - yoff)
        self.pipeline.set(dst=(dst_x, dst_y))
        self.logger.debug("ctr=%d,%d off=%d,%d dst=%d,%d cutout=%dx%d" % (
            ctr_x, ctr_y, xoff, yoff, dst_x, dst_y, wd, ht))

        win_wd, win_ht = state.win_dim
        self.logger.debug("win=%d,%d coverage=%d,%d" % (
            win_wd, win_ht, dst_x + wd, dst_y + ht))

        self.pipeline.send(res_np=data)


class Output(Stage):
    """Create the output image by trimming height and width and reordering
    channels according to viewer settings.
    """

    _stagename = 'viewer-output'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        data = self.pipeline.get_data(prev_stage)

        ## assert (len(data.shape) == 3
        ##         and data.dtype == np.dtype(np.uint8)
        ##         and data.shape[2] in [3, 4]), \
        ##     StageError("Expecting a RGB[A] image in final stage")
        self.verify_2d(data)

        state = self.pipeline.get('state')
        out_order = state.order

        if not self._bypass:
            ht, wd = data.shape[:2]
            state = self.pipeline.get('state')
            win_wd, win_ht = state.win_dim
            if wd < win_wd or ht < win_ht:
                raise StageError("pipeline output doesn't cover window")

            # now cut out the size that we need
            dst_x, dst_y = self.pipeline.get('dst')
            if dst_x > 0 or dst_y > 0:
                raise StageError("pipeline calculated dst is not correct")

            x1, y1 = abs(dst_x), abs(dst_y)
            data = data[y1:y1 + win_ht, x1:x1 + win_wd]

            # reorder image for renderer's desired format
            dst_order = self.viewer.renderer.get_rgb_order()
            data = trcalc.reorder_image(dst_order, data, state.order)
            data = np.ascontiguousarray(data)
            out_order = dst_order

        self.pipeline.set(out_order=out_order)
        self.pipeline.send(res_np=data)


class Overlays(Stage):
    """The Overlays stage constructs an embedded pipeline to process each
    canvas into a RGBA image.  A pipeline is run for each image that
    needs to be processed. The pipeline run depends on the type of image
    on the canvas:

    ginga.canvas.types.image.Image:

    [scale] => [reorder] => [merge]

    ginga.canvas.types.image.NormImage:

    [scale] => [reorder] => [cuts] => [rgbmap] => [merge]
    """

    _stagename = 'viewer-image-overlays'

    def __init__(self, viewer):
        super(Overlays, self).__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        whence = self.pipeline.get('whence')
        dstarr = self.pipeline.get_data(self)
        if whence >= 3 and dstarr is not None:
            # if we are only overplotting (whence >= 3) then we can
            # simply use the result of the last pipeline run because
            # nothing should have changed
            self.pipeline.send(res_np=dstarr)
            return

        bgarr = self.pipeline.get_data(prev_stage)
        self.verify_2d(bgarr)

        dstarr = np.copy(bgarr)
        self.pipeline.set(dstarr=dstarr)

        p_canvas = self.viewer.get_private_canvas()
        self._overlay_images(p_canvas, whence=whence)

        self.pipeline.send(res_np=dstarr)

    def _overlay_images(self, canvas, whence=0.0):
        if not hasattr(canvas, 'objects'):
            return

        for obj in canvas.get_objects():
            if hasattr(obj, 'prepare_image'):
                obj.prepare_image(self.viewer, whence)
            elif obj.is_compound() and (obj != canvas):
                self._overlay_images(obj, whence=whence)

    def _prepare_image(self, cvs_img, cache, whence):
        from ginga.util import pipeline
        pipe = cache.get('minipipe', None)
        if pipe is None:
            stages = [Scale(self.viewer),    # 0
                      Reorder(self.viewer),  # 1
                      Merge(self.viewer)]    # 2
            pipe = pipeline.Pipeline(self.logger, stages)
            pipe.name = 'image-overlays'
            cache.minipipe = pipe
        state = self.pipeline.get('state')
        pipe.set(whence=whence, cvs_img=cvs_img, state=state,
                 dstarr=self.pipeline.get('dstarr'))
        if whence <= 0:
            pipe.run_from(pipe[0])
            return

        if not cache.visible:
            # set by Scale stage depending on image visibility in result
            return
        pipe.run_from(pipe[1])

    def _prepare_norm_image(self, cvs_img, cache, whence):
        from ginga.util import pipeline
        pipe = cache.get('minipipe', None)
        if pipe is None:
            stages = [Scale(self.viewer),    # 0
                      Reorder(self.viewer),  # 1
                      Cuts(self.viewer),     # 2
                      RGBMap(self.viewer),   # 3
                      Merge(self.viewer)]    # 4
            pipe = pipeline.Pipeline(self.logger, stages)
            pipe.name = 'image-overlays'
            cache.minipipe = pipe
        state = self.pipeline.get('state')
        pipe.set(whence=whence, cvs_img=cvs_img, state=state,
                 dstarr=self.pipeline.get('dstarr'))
        if whence <= 0:
            pipe.run_from(pipe[0])
            return

        if not cache.visible:
            # set by Scale stage depending on image visibility in result
            return
        elif whence <= 1:
            pipe.run_from(pipe[2])  # Cuts
        elif whence <= 2:
            pipe.run_from(pipe[3])  # RGBMap
        else:
            pipe.run_from(pipe[4])  # Merge


class Scale(Stage):
    """Scale the image according to the viewers scale settings.  Only the
    portions of the image that will be visible are copied and then scaled.
    """

    _stagename = 'viewer-scale'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        #if prev_stage is not None:
        #    raise StageError(f"'{}' in wrong location".format(self._stagename))
        cvs_img = self.pipeline.get('cvs_img')
        cache = cvs_img.get_cache(self.viewer)

        image = cvs_img.get_image()
        if image is None:
            self.pipeline.send(res_np=None)
            return

        data_np = image.get_data()
        self.verify_2d(data_np)

        # get extent of our data coverage in the window
        # TODO: get rid of padding by fixing get_draw_rect() which
        # doesn't quite get the coverage right at high magnifications
        pad = 1.0
        pts = np.asarray(self.viewer.get_draw_rect()).T
        xmin = int(np.min(pts[0])) - pad
        ymin = int(np.min(pts[1])) - pad
        xmax = int(np.ceil(np.max(pts[0]))) + pad
        ymax = int(np.ceil(np.max(pts[1]))) + pad

        # get destination location in data_coords
        img = cvs_img
        dst_x, dst_y = img.crdmap.to_data((img.x, img.y))

        ht, wd = data_np.shape[:2]
        # TODO: think we need to apply scaling factors to wd/ht
        # BEFORE we calculate merge clip
        a1, b1, a2, b2 = 0, 0, wd - 1, ht - 1

        # calculate the cutout that we can make and scale to merge
        # onto the final image--by only cutting out what is necessary
        # this speeds scaling greatly at zoomed in sizes
        ((dst_x, dst_y), (a1, b1), (a2, b2)) = \
            trcalc.calc_image_merge_clip((xmin, ymin), (xmax, ymax),
                                         (dst_x, dst_y),
                                         (a1, b1), (a2, b2))

        # is image completely off the screen?
        if (a2 - a1 <= 0) or (b2 - b1 <= 0):
            # no overlay needed
            self.pipeline.send(res_np=None)
            cache.visible = False
            self.pipeline.stop()
            return

        cache.visible = True

        # cutout and scale the piece appropriately by the viewer scale
        scale_x, scale_y = self.viewer.get_scale_xy()
        # scale additionally by scale specified in canvas image
        _scale_x, _scale_y = (scale_x * img.scale_x,
                              scale_y * img.scale_y)

        interp = img.interpolation
        if interp is None:
            t_ = self.viewer.get_settings()
            interp = t_.get('interpolation', 'basic')
        if interp not in trcalc.interpolation_methods:
            interp = 'basic'

        data, scales = trcalc.get_scaled_cutout_basic(data_np, a1, b1, a2, b2,
                                                      _scale_x, _scale_y,
                                                      interpolation=interp,
                                                      logger=self.logger)

        if img.flipy:
            data = np.flipud(data)

        # calculate our offset from the pan position
        pan_x, pan_y = self.viewer.get_pan()
        pan_off = self.viewer.data_off
        pan_x, pan_y = pan_x + pan_off, pan_y + pan_off
        off_x, off_y = dst_x - pan_x, dst_y - pan_y
        # scale offset
        off_x *= scale_x
        off_y *= scale_y

        self.pipeline.set(offset=(off_x, off_y))

        self.pipeline.send(res_np=data)


class Reorder(Stage):
    """Reorder RGB images for the pipeline.

    Reorders multiband images for processing in the pipeline standard
    order.  Additionally, if the image has an alpha channel, then strip
    it off and save it until it is recombined later with the colorized
    output--this saves us having to deal with an alpha band in the cuts
    leveling and RGB mapping routines.
    """

    _stagename = 'viewer-reorder'

    def __init__(self, viewer):
        super(Reorder, self).__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        data = self.pipeline.get_data(prev_stage)
        if data is None:
            self.pipeline.send(res_np=None)
            return
        self.verify_2d(data)

        cvs_img = self.pipeline.get('cvs_img')

        state = self.pipeline.get('state')
        image = cvs_img.get_image()
        image_order = image.get_order()

        if isinstance(image, RGBImage.RGBImage) and image_order != state.order:
            # reorder image channels for pipeline
            data = trcalc.reorder_image(state.order, data, image_order)

        # strip off alpha layer, if any
        if 'A' not in image_order:
            alpha = None

        else:
            # strip off alpha layer
            # data, alpha = trcalc.remove_alpha(data)
            a_idx = image_order.index('A')
            alpha = data[..., a_idx]
            data = data[..., 0:a_idx]
            ht, wd, dp = data.shape
            if dp == 1:
                data = data.reshape((ht, wd))

        # currently added back on in Merge stage
        self.pipeline.set(alpha=alpha)

        self.pipeline.send(res_np=data)


class Merge(Stage):
    """Merge the processed image into the result of our stage at the
    appropriate offset and with the appropriate alpha blending.
    """

    _stagename = 'viewer-merge-overlay'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        rgbarr = self.pipeline.get_data(prev_stage)
        if rgbarr is None:
            # nothing to merge
            return
        self.verify_2d(rgbarr)

        if len(rgbarr.shape) != 3 or rgbarr.shape[2] < 3:
            raise StageError("Not an RGB array (shape={})".format(rgbarr.shape))

        cvs_img = self.pipeline.get('cvs_img')
        off_x, off_y = self.pipeline.get('offset')
        dstarr = self.pipeline.get('dstarr')
        state = self.pipeline.get('state')

        # dst position in the pre-transformed array should be calculated
        # from the center of the array plus offsets
        ht, wd, dp = dstarr.shape
        cvs_x = int(np.round(wd * 0.5 + off_x))
        cvs_y = int(np.round(ht * 0.5 + off_y))
        cvs_pos = (cvs_x, cvs_y)

        dst_order = state.order
        image_order = state.order

        # merge back in alpha layer if one was stripped off earler
        # in the pipeline
        alpha = self.pipeline.get('alpha')
        if alpha is not None and 'A' in state.order:
            a_idx = state.order.index('A')
            if rgbarr.shape[2] != 4:
                #raise StageError("RGB array lacks alpha band (shape={})".format(rgbarr.shape))
                # insert an empty alpha layer to accomodate
                rgbarr = np.insert(rgbarr, a_idx,
                                   np.zeros(rgbarr.shape[:2],
                                            dtype=rgbarr.dtype),
                                   axis=2)
            # normalize alpha array to the final output range
            alpha = trcalc.array_convert(alpha, rgbarr.dtype)
            rgbarr[..., a_idx] = alpha

        # composite the image into the destination array at the
        # calculated position
        trcalc.overlay_image(dstarr, cvs_pos, rgbarr,
                             dst_order=dst_order, src_order=image_order,
                             # NOTE: these actually not used because rgbarr
                             # contains an alpha channel
                             alpha=cvs_img.alpha, fill=True,
                             flipy=False)   # cvs_img.flipy

        cache = cvs_img.get_cache(self.viewer)
        cache.drawn = True
        #self.pipeline.send(res_np=None)


class Cuts(Stage):
    """Process the cut levels (loval, hival) for the image.

    This has the effect of mapping every input value between loval and
    hival to the range specified by the output values (vmin, vmax).
    Input values lower than loval are mapped to loval and values higher
    than hival are mapped to hival.
    """

    _stagename = 'viewer-cut-levels'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        data = self.pipeline.get_data(prev_stage)
        if data is None:
            self.pipeline.send(res_np=None)
            return
        self.verify_2d(data)

        cvs_img = self.pipeline.get('cvs_img')

        if cvs_img.rgbmap is not None:
            rgbmap = cvs_img.rgbmap
        else:
            rgbmap = self.viewer.get_rgbmap()

        vmin = 0
        vmax = rgbmap.get_hash_size() - 1

        if cvs_img.autocuts is not None:
            autocuts = cvs_img.autocuts
        else:
            autocuts = self.viewer.autocuts

        # Apply cut levels
        if cvs_img.cuts is not None:
            loval, hival = cvs_img.cuts
        else:
            loval, hival = self.viewer.t_['cuts']

        res_np = autocuts.cut_levels(data, loval, hival,
                                     vmin=vmin, vmax=vmax)

        # NOTE: optimization to prevent multiple coercions in
        # RGBMap
        if not np.issubdtype(res_np.dtype, np.uint):
            res_np = res_np.astype(np.uint)

        self.pipeline.send(res_np=res_np)


class RGBMap(Stage):
    """Color map an image using a RGBMap.

    This color-maps an image according to the settings in the RGBMap
    of the image (if it has one), or the viewer (if not).
    """

    _stagename = 'viewer-rgb-mapper'

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer

    def run(self, prev_stage):
        arr_in = self.pipeline.get_data(prev_stage)
        if arr_in is None:
            self.pipeline.send(res_np=None)
            return
        self.verify_2d(arr_in)

        cvs_img = self.pipeline.get('cvs_img')
        state = self.pipeline.get('state')

        if cvs_img.rgbmap is not None:
            rgbmap = cvs_img.rgbmap
        else:
            rgbmap = self.viewer.get_rgbmap()

        # See NOTE in Cuts
        if not np.issubdtype(arr_in.dtype, np.dtype(np.uint)):
            arr_in = arr_in.astype(np.uint)

        # get RGB mapped array
        arr_out = rgbmap.get_rgb_array(arr_in, order=state.order)

        self.pipeline.send(res_np=arr_out)
