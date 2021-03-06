from __future__ import division
import warnings
from menpo.feature import no_op
from menpo.visualize import print_dynamic
from menpofit import checks
from menpofit.base import batch
from menpofit.builder import (
    compute_features, scale_images, build_shape_model, increment_shape_model,
    MenpoFitBuilderWarning, compute_reference_shape,
    rescale_images_to_reference_shape)
from .expert import ExpertEnsemble, CorrelationFilterExpertEnsemble


# TODO: Document me!
# TODO: Introduce shape_model_cls
# TODO: Get rid of max_shape_components and shape_forgetting_factor
class CLM(object):
    r"""
    Constrained Local Model (CLM) class.

    Parameters
    ----------

    Returns
    -------
    clm : :map:`CLM`
        The CLM object
    """
    def __init__(self, images, group=None, verbose=False, batch_size=None,
                 diagonal=None, scales=(0.5, 1), holistic_features=no_op,
                 # shape_model_cls=build_normalised_pca_shape_model,
                 expert_ensemble_cls=CorrelationFilterExpertEnsemble,
                 max_shape_components=None, reference_shape=None,
                 shape_forgetting_factor=1.0):
        self.diagonal = checks.check_diagonal(diagonal)
        self.scales = checks.check_scales(scales)
        self.holistic_features = checks.check_features(holistic_features,
                                                       self.n_scales)
        # self.shape_model_cls = checks.check_algorithm_cls(
        #     shape_model_cls, self.n_scales, ShapeModel)
        self.expert_ensemble_cls = checks.check_algorithm_cls(
            expert_ensemble_cls, self.n_scales, ExpertEnsemble)

        self.max_shape_components = checks.check_max_components(
            max_shape_components, self.n_scales, 'max_shape_components')
        self.shape_forgetting_factor = shape_forgetting_factor
        self.reference_shape = reference_shape
        self.shape_models = []
        self.expert_ensembles = []

        # Train CLM
        self._train(images, increment=False, group=group, verbose=verbose,
                    batch_size=batch_size)

    @property
    def n_scales(self):
        r"""
        The number of scales of the CLM.

        :type: `int`
        """
        return len(self.scales)

    def _train(self, images, increment=False, group=None, verbose=False,
               batch_size=None):
        r"""
        """
        # If batch_size is not None, then we may have a generator, else we
        # assume we have a list.
        # If batch_size is not None, then we may have a generator, else we
        # assume we have a list.
        if batch_size is not None:
            # Create a generator of fixed sized batches. Will still work even
            # on an infinite list.
            image_batches = batch(images, batch_size)
        else:
            image_batches = [list(images)]

        for k, image_batch in enumerate(image_batches):
            if k == 0:
                if self.reference_shape is None:
                    # If no reference shape was given, use the mean of the first
                    # batch
                    if batch_size is not None:
                        warnings.warn('No reference shape was provided. The '
                                      'mean of the first batch will be the '
                                      'reference shape. If the batch mean is '
                                      'not representative of the true mean, '
                                      'this may cause issues.',
                                      MenpoFitBuilderWarning)
                    self.reference_shape = compute_reference_shape(
                        [i.landmarks[group].lms for i in image_batch],
                        self.diagonal, verbose=verbose)

            # After the first batch, we are incrementing the model
            if k > 0:
                increment = True

            if verbose:
                print('Computing batch {}'.format(k))

            # Train each batch
            self._train_batch(image_batch, increment=increment, group=group,
                              verbose=verbose)

    def _train_batch(self, image_batch, increment=False, group=None,
                     verbose=False):
        r"""
        """
        # normalize images
        image_batch = rescale_images_to_reference_shape(
            image_batch, group, self.reference_shape, verbose=verbose)

        # build models at each scale
        if verbose:
            print_dynamic('- Training models\n')

        # for each level (low --> high)
        for i in range(self.n_scales):
            if verbose:
                if self.n_scales > 1:
                    prefix = '  - Scale {}: '.format(i)
                else:
                    prefix = '  - '
            else:
                prefix = None

            # Handle holistic features
            if i == 0 and self.holistic_features[i] == no_op:
                # Saves a lot of memory
                feature_images = image_batch
            elif i == 0 or self.holistic_features[i] is not self.holistic_features[i - 1]:
                # compute features only if this is the first pass through
                # the loop or the features at this scale are different from
                # the features at the previous scale
                feature_images = compute_features(image_batch,
                                                  self.holistic_features[i],
                                                  prefix=prefix,
                                                  verbose=verbose)
            # handle scales
            if self.scales[i] != 1:
                # scale feature images only if scale is different than 1
                scaled_images = scale_images(feature_images,
                                             self.scales[i],
                                             prefix=prefix,
                                             verbose=verbose)
            else:
                scaled_images = feature_images

            # extract scaled shapes
            scaled_shapes = [image.landmarks[group].lms
                             for image in scaled_images]

            # train shape model
            if verbose:
                print_dynamic('{}Training shape model'.format(prefix))

            # TODO: This should be cleaned up by defining shape model classes
            if increment:
                increment_shape_model(
                    self.shape_models[i], scaled_shapes,
                    max_components=self.max_shape_components[i],
                    forgetting_factor=self.shape_forgetting_factor,
                    prefix=prefix, verbose=verbose)

            else:
                shape_model = build_shape_model(
                    scaled_shapes, max_components=self.max_shape_components[i],
                    prefix=prefix, verbose=verbose)
                self.shape_models.append(shape_model)

            # train expert ensemble
            if verbose:
                print_dynamic('{}Training expert ensemble'.format(prefix))

            if increment:
                self.expert_ensembles[i].increment(scaled_images,
                                                   scaled_shapes,
                                                   prefix=prefix,
                                                   verbose=verbose)
            else:
                expert_ensemble = self.expert_ensemble_cls[i](scaled_images,
                                                              scaled_shapes,
                                                              prefix=prefix,
                                                              verbose=verbose)
                self.expert_ensembles.append(expert_ensemble)

            if verbose:
                print_dynamic('{}Done\n'.format(prefix))

    def increment(self, images, group=None, verbose=False, batch_size=None):
        r"""
        """
        return self._train(images, increment=True, group=group, verbose=verbose,
                           batch_size=batch_size)

    def view_shape_models_widget(self, n_parameters=5,
                                 parameters_bounds=(-3.0, 3.0),
                                 mode='multiple', figure_size=(10, 8)):
        r"""
        Visualizes the shape models of the AAM object using an interactive
        widget.

        Parameters
        -----------
        n_parameters : `int` or `list` of `int` or ``None``, optional
            The number of shape principal components to be used for the
            parameters sliders.
            If `int`, then the number of sliders per level is the minimum
            between `n_parameters` and the number of active components per
            level.
            If `list` of `int`, then a number of sliders is defined per level.
            If ``None``, all the active components per level will have a slider.
        parameters_bounds : (`float`, `float`), optional
            The minimum and maximum bounds, in std units, for the sliders.
        mode : {``single``, ``multiple``}, optional
            If ``'single'``, only a single slider is constructed along with a
            drop down menu.
            If ``'multiple'``, a slider is constructed for each parameter.
        popup : `bool`, optional
            If ``True``, the widget will appear as a popup window.
        figure_size : (`int`, `int`), optional
            The size of the plotted figures.
        """
        try:
            from menpowidgets import visualize_shape_model
            visualize_shape_model(self.shape_models, n_parameters=n_parameters,
                                  parameters_bounds=parameters_bounds,
                                  figure_size=figure_size, mode=mode,)
        except:
            from menpo.visualize.base import MenpowidgetsMissingError
            raise MenpowidgetsMissingError()

    # TODO: Implement me!
    def view_expert_ensemble_widget(self):
        r"""
        """
        raise NotImplementedError

    # TODO: Implement me!
    def view_clm_widget(self):
        r"""
        """
        raise NotImplementedError

    # TODO: Implement me!
    def __str__(self):
        r"""
        """
        raise NotImplementedError
