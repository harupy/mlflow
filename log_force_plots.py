import shap

explainer = "shap explainer object"
features = "numpy.array or pandas.DataFrame"

####################################################################################################
# regression or binary classification (where `predict` returns a 1D array)
####################################################################################################

# questions
# should we allow the user to select samples to create single-force-plot for?
shap_values = explainer(features)
print(shap_values.shape)  # -> (num_samples, num_features)
force_plot_single = shap.force_plot(explainer.expected_value, shap_values[0], features.iloc[0])
force_plot_all = shap.force_plot(explainer.expected_value, shap_values, features)
summar_scatter = shap.summary_plot(shap_values, features)

####################################################################################################
# multi-class classification (where `predict` returns a 2D array)
####################################################################################################

shap_values_by_label = explainer(features)
print(shap_values_by_label.shape)  # -> (num_classes, num_samples, num_features)

# When the number of labels is large, ...
# option 1: Log all plots
# option 2: Introduce an argument to specify features to plot
for label_index, shap_values in enumerate(shap_values):
    force_plot_single = shap.force_plot(explainer.expected_value, shap_values[0], features.iloc[0])
    force_plot_all = shap.force_plot(explainer.expected_value[label_index], shap_values, features)
    summar_scatter = shap.summary_plot(shap_values, features)


We usually have both trained model and features in the autolog function.