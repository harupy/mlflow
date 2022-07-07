import React from 'react';
import Utils from '../../common/utils/Utils';
import _ from 'lodash';
import PropTypes from 'prop-types';
import { saveAs } from 'file-saver';
import { Icons } from 'plotly.js';
import { Modal } from 'antd';

import { X_AXIS_STEP, X_AXIS_RELATIVE, MAX_LINE_SMOOTHNESS } from './MetricsPlotControls';
import { CHART_TYPE_BAR, convertMetricsToCsv } from './MetricsPlotPanel';
import { LazyPlot } from './LazyPlot';
import { ColorPaletteModal } from './ColorPaletteModal';

const MAX_RUN_NAME_DISPLAY_LENGTH = 24;

const EMA = (mArray, smoothingWeight) => {
  // If all elements in the set of metric values are constant, or if
  // the degree of smoothing is set to the minimum value, return the
  // original set of metric values
  if (smoothingWeight <= 1 || mArray.every((v) => v === mArray[0])) {
    return mArray;
  }

  const smoothness = smoothingWeight / (MAX_LINE_SMOOTHNESS + 1);
  const smoothedArray = [];
  let biasedElement = 0;
  for (let i = 0; i < mArray.length; i++) {
    if (!isNaN(mArray[i])) {
      biasedElement = biasedElement * smoothness + (1 - smoothness) * mArray[i];
      // To avoid biasing earlier elements toward smaller-than-accurate values, we divide
      // all elements by a `debiasedWeight` that asymptotically increases and approaches
      // 1 as the element index increases
      const debiasWeight = 1.0 - Math.pow(smoothness, i + 1);
      const debiasedElement = biasedElement / debiasWeight;
      smoothedArray.push(debiasedElement);
    } else {
      smoothedArray.push(mArray[i]);
    }
  }
  return smoothedArray;
};

export class MetricsPlotView extends React.Component {
  state = {
    colorway: undefined,
    colorPaletteVisible: false,
  };
  static propTypes = {
    runUuids: PropTypes.arrayOf(PropTypes.string).isRequired,
    runDisplayNames: PropTypes.arrayOf(PropTypes.string).isRequired,
    metrics: PropTypes.arrayOf(PropTypes.object).isRequired,
    xAxis: PropTypes.string.isRequired,
    metricKeys: PropTypes.arrayOf(PropTypes.string).isRequired,
    // Whether or not to show point markers on the line chart
    showPoint: PropTypes.bool.isRequired,
    chartType: PropTypes.string.isRequired,
    isComparing: PropTypes.bool.isRequired,
    lineSmoothness: PropTypes.number,
    extraLayout: PropTypes.object,
    onLayoutChange: PropTypes.func.isRequired,
    onClick: PropTypes.func.isRequired,
    onLegendClick: PropTypes.func.isRequired,
    onLegendDoubleClick: PropTypes.func.isRequired,
    deselectedCurves: PropTypes.arrayOf(PropTypes.string).isRequired,
  };

  static getLineLegend = (metricKey, runDisplayName, isComparing) => {
    let legend = metricKey;
    if (isComparing) {
      legend += `, ${Utils.truncateString(runDisplayName, MAX_RUN_NAME_DISPLAY_LENGTH)}`;
    }
    return legend;
  };

  static parseTimestamp = (timestamp, history, xAxis) => {
    if (xAxis === X_AXIS_RELATIVE) {
      const minTimestamp = _.minBy(history, 'timestamp').timestamp;
      return (timestamp - minTimestamp) / 1000;
    }
    return Utils.formatTimestamp(timestamp);
  };

  getPlotPropsForLineChart = () => {
    const { metrics, xAxis, showPoint, lineSmoothness, isComparing, deselectedCurves } = this.props;
    const deselectedCurvesSet = new Set(deselectedCurves);
    const data = metrics.map((metric) => {
      const { metricKey, runDisplayName, history, runUuid } = metric;
      const historyValues = history.map((entry) =>
        typeof entry.value === 'number' ? entry.value : Number(entry.value),
      );
      // For metrics with exactly one non-NaN item, we set `isSingleHistory` to `true` in order
      // to display the item as a point. For metrics with zero non-NaN items (i.e., empty metrics),
      // we also set `isSingleHistory` to `true` in order to populate the plot legend with a
      // point-style entry for each empty metric, although no data will be plotted for empty
      // metrics
      const isSingleHistory = historyValues.filter((value) => !isNaN(value)).length <= 1;
      const visible = !deselectedCurvesSet.has(Utils.getCurveKey(runUuid, metricKey))
        ? true
        : 'legendonly';
      return {
        name: MetricsPlotView.getLineLegend(metricKey, runDisplayName, isComparing),
        x: history.map((entry) => {
          if (xAxis === X_AXIS_STEP) {
            return entry.step;
          }
          return MetricsPlotView.parseTimestamp(entry.timestamp, history, xAxis);
        }),
        y: isSingleHistory ? historyValues : EMA(historyValues, lineSmoothness),
        text: historyValues.map((value) => (isNaN(value) ? value : value.toFixed(5))),
        type: 'scattergl',
        mode: isSingleHistory ? 'markers' : 'lines+markers',
        marker: { opacity: isSingleHistory || showPoint ? 1 : 0 },
        hovertemplate:
          isSingleHistory || lineSmoothness === 1 ? '%{y}' : 'Value: %{text}<br>Smoothed: %{y}',
        visible: visible,
        runId: runUuid,
        metricName: metricKey,
      };
    });
    const props = { data };
    props.layout = {
      ...props.layout,
      ...this.props.extraLayout,
    };
    return props;
  };

  getPlotPropsForBarChart = () => {
    /* eslint-disable no-param-reassign */
    const { runUuids, runDisplayNames, deselectedCurves } = this.props;

    // A reverse lookup of `metricKey: { runUuid: value, metricKey }`
    const historyByMetricKey = this.props.metrics.reduce((map, metric) => {
      const { runUuid, metricKey, history } = metric;
      const value = history[0] && history[0].value;
      if (!map[metricKey]) {
        map[metricKey] = { metricKey, [runUuid]: value };
      } else {
        map[metricKey][runUuid] = value;
      }
      return map;
    }, {});

    const arrayOfHistorySortedByMetricKey = _.sortBy(
      Object.values(historyByMetricKey),
      'metricKey',
    );

    const sortedMetricKeys = arrayOfHistorySortedByMetricKey.map((history) => history.metricKey);
    const deselectedCurvesSet = new Set(deselectedCurves);
    const data = runUuids.map((runUuid, i) => {
      const visibility = deselectedCurvesSet.has(runUuid) ? { visible: 'legendonly' } : {};
      return {
        name: Utils.truncateString(runDisplayNames[i], MAX_RUN_NAME_DISPLAY_LENGTH),
        x: sortedMetricKeys,
        y: arrayOfHistorySortedByMetricKey.map((history) => history[runUuid]),
        type: 'bar',
        runId: runUuid,
        ...visibility,
      };
    });

    const layout = { barmode: 'group' };
    const props = { data, layout };
    props.layout = {
      ...props.layout,
      ...this.props.extraLayout,
    };
    return props;
  };

  render() {
    const { onLayoutChange, onClick, onLegendClick, onLegendDoubleClick } = this.props;
    const plotProps =
      this.props.chartType === CHART_TYPE_BAR
        ? this.getPlotPropsForBarChart()
        : this.getPlotPropsForLineChart();
    return (
      <div className='metrics-plot-view-container'>
        <ColorPaletteModal
          visible={this.state.colorPaletteVisible}
          onSelect={(colors) => this.setState({ colorway: colors })}
          onCancel={() => this.setState({ colorPaletteVisible: false })}
        />
        <LazyPlot
          {...plotProps}
          useResizeHandler
          onRelayout={onLayoutChange}
          onClick={onClick}
          onLegendClick={onLegendClick}
          onLegendDoubleClick={onLegendDoubleClick}
          style={{ width: '100%', height: '100%' }}
          layout={{
            ..._.cloneDeep(plotProps.layout),
            colorway: this.state.colorway,
          }}
          config={{
            displaylogo: false,
            scrollZoom: true,
            modeBarButtonsToRemove: ['sendDataToCloud'],
            modeBarButtonsToAdd: [
              {
                name: 'Download plot data as CSV',
                icon: Icons.disk,
                click: () => {
                  const csv = convertMetricsToCsv(this.props.metrics);
                  const blob = new Blob([csv], { type: 'application/csv;charset=utf-8' });
                  saveAs(blob, 'metrics.csv');
                },
              },
              {
                name: 'Select color palette',
                icon: {
                  width: 1000,
                  height: 1000,
                  transform: 'translate(0.000000,511.000000) scale(0.100000,-0.100000)',
                  path: 'M4630.5,4991.4c-890.5-85.1-1659.1-349.7-2335.6-800.8C240.1,2816.9-482.5,159.1,601.3-2045.3C1319.3-3501.9,2670-4489.1,4287.7-4742.2c315.2-48.3,1090.7-55.2,1355.3-11.5c453.3,75.9,777.8,388.9,853.7,828.4c32.2,184.1,0,379.7-98.9,579.9c-57.5,119.7-149.6,227.8-460.2,543.1c-418.8,428-480.9,520-529.2,791.6c-62.1,354.4,115.1,768.6,409.6,964.2c59.8,39.1,165.7,94.3,237,122c128.8,52.9,135.7,52.9,1624.6,64.4l1495.7,11.5l149.6,71.3C9692.9-600.2,9900-266.6,9900,152.2c0,434.9-105.8,1053.9-255.4,1502.6c-614.4,1836.3-2255.1,3138.7-4194.9,3327.4C5215,5005.2,4816.9,5009.8,4630.5,4991.4z M5399.1,3953.6c628.2-294.5,782.4-1083.8,310.6-1580.8c-483.2-510.8-1311.6-365.9-1615.4,283c-66.7,142.7-71.3,172.6-73.6,395.8c0,225.5,4.6,253.1,73.6,398.1c92,193.3,264.6,379.7,441.8,474c181.8,96.7,278.4,117.3,513.1,108.2C5212.7,4025,5274.8,4011.2,5399.1,3953.6z M2720.6,2062.1c186.4-34.5,354.4-121.9,494.7-255.4c232.4-220.9,322.1-439.5,306-766.3c-6.9-174.9-20.7-234.7-80.5-363.6c-101.3-214-250.8-368.2-462.5-471.7c-151.9-75.9-195.6-87.4-384.3-94.3c-326.8-13.8-550,73.6-768.6,306c-368.2,388.9-356.7,989.5,20.7,1369.1C2080.9,2018.4,2407.7,2122,2720.6,2062.1z M7624.2,2062.1c418.8-80.5,736.3-407.3,807.7-835.3c75.9-462.5-225.5-934.2-692.6-1086.1c-92-29.9-174.9-36.8-335.9-29.9c-188.7,6.9-232.4,18.4-384.3,94.3c-211.7,103.5-361.3,257.7-462.5,471.7c-69,145-73.6,170.3-73.6,407.3c2.3,326.8,50.6,457.9,246.2,669.6C6975.3,2016.1,7290.6,2124.3,7624.2,2062.1z',
                },
                click: () => {
                  this.setState({ colorPaletteVisible: true });
                },
              },
            ],
          }}
        />
      </div>
    );
  }
}
