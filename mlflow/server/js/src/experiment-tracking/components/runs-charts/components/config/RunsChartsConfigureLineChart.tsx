import {
  Radio,
  LegacySelect,
  Switch,
  Tooltip,
  QuestionMarkIcon,
  Form,
  useDesignSystemTheme,
  ThemeType,
  SegmentedControlGroup,
  SegmentedControlButton,
  InfoIcon,
} from '@databricks/design-system';
import { FormattedMessage, useIntl } from 'react-intl';
import { useCallback, useEffect, useState } from 'react';
import type { RunsChartsCardConfig, RunsChartsLineCardConfig } from '../../runs-charts.types';
import { RunsChartsConfigureField, RunsChartsRunNumberSelect } from './RunsChartsConfigure.common';
import { shouldEnableDeepLearningUIPhase3 } from 'common/utils/FeatureUtils';
import { RunsChartsLineChartXAxisType } from 'experiment-tracking/components/runs-charts/components/RunsCharts.common';
import { LineSmoothSlider } from 'experiment-tracking/components/LineSmoothSlider';

const renderMetricSelectorV1 = ({
  metricKeyList,
  metricKey,
  updateMetric,
}: {
  metricKeyList: string[];
  metricKey?: string;
  updateMetric: (metricKey: string) => void;
}) => {
  const emptyMetricsList = metricKeyList.length === 0;

  return (
    <LegacySelect
      css={styles.selectFull}
      value={emptyMetricsList ? 'No metrics available' : metricKey}
      onChange={updateMetric}
      disabled={emptyMetricsList}
      dangerouslySetAntdProps={{ showSearch: true }}
    >
      {metricKeyList.map((metric) => (
        <LegacySelect.Option key={metric} value={metric} data-testid={`metric-${metric}`}>
          {metric}
        </LegacySelect.Option>
      ))}
    </LegacySelect>
  );
};

const renderMetricSelectorV2 = ({
  metricKeyList,
  selectedMetricKeys,
  updateSelectedMetrics,
}: {
  metricKeyList: string[];
  selectedMetricKeys?: string[];
  updateSelectedMetrics: (metricKeys: string[]) => void;
}) => {
  const emptyMetricsList = metricKeyList.length === 0;

  return (
    <LegacySelect
      mode="multiple"
      placeholder={
        emptyMetricsList ? (
          <FormattedMessage
            defaultMessage="No metrics available"
            description="Text shown in a disabled multi-selector when there are no selectable metrics."
          />
        ) : (
          <FormattedMessage
            defaultMessage="Select metrics"
            description="Placeholder text for a metric multi-selector when configuring a line chart"
          />
        )
      }
      css={styles.selectFull}
      value={emptyMetricsList ? [] : selectedMetricKeys}
      onChange={updateSelectedMetrics}
      disabled={emptyMetricsList}
      dangerouslySetAntdProps={{ showSearch: true }}
    >
      {metricKeyList.map((metric) => (
        <LegacySelect.Option key={metric} value={metric} data-testid={`metric-${metric}`}>
          {metric}
        </LegacySelect.Option>
      ))}
    </LegacySelect>
  );
};

const renderXAxisMetricSelector = ({
  theme,
  metricKeyList,
  selectedXAxisMetricKey,
  updateSelectedXAxisMetricKey,
}: {
  theme: ThemeType;
  metricKeyList: string[];
  selectedXAxisMetricKey?: string;
  updateSelectedXAxisMetricKey: (metricKey: string) => void;
}) => {
  const emptyMetricsList = metricKeyList.length === 0;

  return (
    <Radio value={RunsChartsLineChartXAxisType.METRIC}>
      <FormattedMessage
        defaultMessage="Metric"
        description="Label for a radio button that configures the x-axis on a line chart. This option makes the X-axis a custom metric that the user selects."
      />
      <LegacySelect
        css={{
          marginTop: theme.spacing.xs,
          width: '100%',
        }}
        value={selectedXAxisMetricKey || undefined}
        placeholder={
          emptyMetricsList ? (
            <FormattedMessage
              defaultMessage="No metrics available"
              description="Text shown in a disabled metric selector when there are no selectable metrics."
            />
          ) : (
            <FormattedMessage
              defaultMessage="Select metric"
              description="Placeholder text for a metric selector when configuring a line chart"
            />
          )
        }
        onClick={(e: React.MouseEvent<HTMLElement>) => {
          // this is to prevent the radio button
          // from automatically closing the selector
          e.preventDefault();
          e.stopPropagation();
        }}
        onChange={updateSelectedXAxisMetricKey}
        disabled={emptyMetricsList}
        dangerouslySetAntdProps={{ showSearch: true }}
      >
        {metricKeyList.map((metric) => (
          <LegacySelect.Option key={metric} value={metric} data-testid={`metric-${metric}`}>
            {metric}
          </LegacySelect.Option>
        ))}
      </LegacySelect>
    </Radio>
  );
};

/**
 * Form containing configuration controls for runs compare charts.
 */
export const RunsChartsConfigureLineChart = ({
  state,
  onStateChange,
  metricKeyList,
}: {
  metricKeyList: string[];
  state: Partial<RunsChartsLineCardConfig>;
  onStateChange: (setter: (current: RunsChartsCardConfig) => RunsChartsLineCardConfig) => void;
}) => {
  const shouldEnableMetricsOnXAxis = shouldEnableDeepLearningUIPhase3();
  const { theme } = useDesignSystemTheme();
  const intl = useIntl();
  const runSelectOptions = [5, 10, 20, 50, 100];

  /**
   * Callback for updating metric key
   */
  const updateMetric = useCallback(
    (metricKey: string) => {
      onStateChange((current) => ({ ...(current as RunsChartsLineCardConfig), metricKey }));
    },
    [onStateChange],
  );

  const updateSelectedMetrics = useCallback(
    (metricKeys: string[]) => {
      onStateChange((current) => ({
        ...(current as RunsChartsLineCardConfig),
        metricKey: metricKeys[0],
        selectedMetricKeys: metricKeys,
      }));
    },
    [onStateChange],
  );

  const updateXAxisKey = useCallback(
    (xAxisKey: RunsChartsLineCardConfig['xAxisKey']) => {
      onStateChange((current) => ({
        ...(current as RunsChartsLineCardConfig),
        xAxisKey,
        selectedXAxisMetricKey: '',
      }));
    },
    [onStateChange],
  );

  const updateXAxisScaleType = useCallback(
    (isLogType: boolean) => {
      onStateChange((current) => ({
        ...(current as RunsChartsLineCardConfig),
        xAxisScaleType: isLogType ? 'log' : 'linear',
      }));
    },
    [onStateChange],
  );

  const updateSelectedXAxisMetricKey = useCallback(
    (selectedXAxisMetricKey: string) => {
      onStateChange((current) => ({
        ...(current as RunsChartsLineCardConfig),
        selectedXAxisMetricKey,
        xAxisKey: RunsChartsLineChartXAxisType.METRIC,
      }));
    },
    [onStateChange],
  );

  const updateYAxisType = useCallback(
    (isLogType: boolean) =>
      onStateChange((current) => ({
        ...(current as RunsChartsLineCardConfig),
        scaleType: isLogType ? 'log' : 'linear',
      })),
    [onStateChange],
  );

  const updateSmoothing = useCallback(
    (lineSmoothness: number) => {
      onStateChange((current) => ({
        ...(current as RunsChartsLineCardConfig),
        lineSmoothness: lineSmoothness,
      }));
    },
    [onStateChange],
  );

  /**
   * Callback for updating run count
   */
  const updateVisibleRunCount = useCallback(
    (runsCountToCompare: number) => {
      onStateChange((current) => ({
        ...(current as RunsChartsLineCardConfig),
        runsCountToCompare,
      }));
    },
    [onStateChange],
  );

  /**
   * If somehow metric key is not predetermined, automatically
   * select the first one so it's not empty
   */
  useEffect(() => {
    if (!state.metricKey && metricKeyList?.[0]) {
      updateMetric(metricKeyList[0]);
    }
  }, [state.metricKey, updateMetric, metricKeyList]);

  // for backwards compatibility, if selectedMetricKeys
  // is not present, set it using metricKey.
  useEffect(() => {
    if (state.selectedMetricKeys === undefined && state.metricKey !== undefined && state.metricKey !== '') {
      updateSelectedMetrics([state.metricKey]);
    }
  }, [state.selectedMetricKeys, state.metricKey, updateSelectedMetrics]);

  return (
    <>
      <RunsChartsConfigureField title="Metric (Y-axis)">
        {renderMetricSelectorV2({
          metricKeyList,
          selectedMetricKeys: state.selectedMetricKeys,
          updateSelectedMetrics,
        })}
      </RunsChartsConfigureField>
      <RunsChartsConfigureField title="X-axis">
        <Radio.Group
          name="runs-charts-field-group-x-axis"
          value={state.xAxisKey}
          onChange={({ target: { value } }) => updateXAxisKey(value)}
        >
          <Radio value={RunsChartsLineChartXAxisType.STEP}>
            <FormattedMessage
              defaultMessage="Step"
              description="Label for a radio button that configures the x-axis on a line chart. This option is for the step number that the metrics were logged."
            />
          </Radio>
          <Radio value={RunsChartsLineChartXAxisType.TIME}>
            <FormattedMessage
              defaultMessage="Time (wall)"
              description="Label for a radio button that configures the x-axis on a line chart. This option is for the absolute time that the metrics were logged."
            />
            <Tooltip
              title={
                <FormattedMessage
                  defaultMessage="Absolute date and time"
                  description="A tooltip line chart configuration for the step function of wall time"
                />
              }
              placement="right"
            >
              {' '}
              <QuestionMarkIcon css={styles.timeStepQuestionMarkIcon} />
            </Tooltip>
          </Radio>
          <Radio value={RunsChartsLineChartXAxisType.TIME_RELATIVE}>
            <FormattedMessage
              defaultMessage="Time (relative)"
              description="Label for a radio button that configures the x-axis on a line chart. This option is for relative time since the first metric was logged."
            />
            <Tooltip
              title={
                <FormattedMessage
                  defaultMessage="Amount of time that has passed since the first metric value was logged"
                  description="A tooltip line chart configuration for the step function of relative time"
                />
              }
              placement="right"
            >
              {' '}
              <QuestionMarkIcon css={styles.timeStepQuestionMarkIcon} />
            </Tooltip>
          </Radio>
          {shouldEnableMetricsOnXAxis &&
            renderXAxisMetricSelector({
              theme,
              metricKeyList,
              selectedXAxisMetricKey: state.selectedXAxisMetricKey,
              updateSelectedXAxisMetricKey,
            })}
        </Radio.Group>
      </RunsChartsConfigureField>
      {state.xAxisKey === RunsChartsLineChartXAxisType.STEP && (
        <RunsChartsConfigureField title="X-axis log scale">
          <Switch checked={state.xAxisScaleType === 'log'} onChange={updateXAxisScaleType} label="Enabled" />
        </RunsChartsConfigureField>
      )}
      <RunsChartsConfigureField title="Y-axis log scale">
        <Switch checked={state.scaleType === 'log'} onChange={updateYAxisType} label="Enabled" />
      </RunsChartsConfigureField>
      <RunsChartsConfigureField
        title={intl.formatMessage({
          defaultMessage: 'Display points',
          description: 'Runs charts > line chart > display points > label',
        })}
      >
        <SegmentedControlGroup
          name={intl.formatMessage({
            defaultMessage: 'Display points',
            description: 'Runs charts > line chart > display points > label',
          })}
          value={state.displayPoints}
          onChange={({ target }) => {
            onStateChange((current) => ({
              ...(current as RunsChartsLineCardConfig),
              displayPoints: target.value,
            }));
          }}
        >
          <SegmentedControlButton
            value={undefined}
            aria-label={[
              intl.formatMessage({
                defaultMessage: 'Display points',
                description: 'Runs charts > line chart > display points > label',
              }),
              intl.formatMessage({
                defaultMessage: 'Auto',
                description: 'Runs charts > line chart > display points > auto setting label',
              }),
            ].join(': ')}
          >
            <FormattedMessage
              defaultMessage="Auto"
              description="Runs charts > line chart > display points > auto setting label"
            />{' '}
            <Tooltip
              title={
                <FormattedMessage
                  defaultMessage="Show points on line charts if there are fewer than 60 data points per trace"
                  description="Runs charts > line chart > display points > auto tooltip"
                />
              }
            >
              <InfoIcon />
            </Tooltip>
          </SegmentedControlButton>
          <SegmentedControlButton
            value
            aria-label={[
              intl.formatMessage({
                defaultMessage: 'Display points',
                description: 'Runs charts > line chart > display points > label',
              }),
              intl.formatMessage({
                defaultMessage: 'On',
                description: 'Runs charts > line chart > display points > on setting label',
              }),
            ].join(': ')}
          >
            <FormattedMessage
              defaultMessage="On"
              description="Runs charts > line chart > display points > on setting label"
            />
          </SegmentedControlButton>
          <SegmentedControlButton
            value={false}
            aria-label={[
              intl.formatMessage({
                defaultMessage: 'Display points',
                description: 'Runs charts > line chart > display points > label',
              }),
              intl.formatMessage({
                defaultMessage: 'Off',
                description: 'Runs charts > line chart > display points > off setting label',
              }),
            ].join(': ')}
          >
            <FormattedMessage
              defaultMessage="Off"
              description="Runs charts > line chart > display points > off setting label"
            />
          </SegmentedControlButton>
        </SegmentedControlGroup>
      </RunsChartsConfigureField>
      <RunsChartsConfigureField title="Line smoothness">
        <LineSmoothSlider
          data-testid="smoothness-toggle"
          min={0}
          max={100}
          onChange={updateSmoothing}
          defaultValue={state.lineSmoothness ? state.lineSmoothness : 0}
        />
      </RunsChartsConfigureField>
      <RunsChartsRunNumberSelect
        value={state.runsCountToCompare}
        onChange={updateVisibleRunCount}
        options={runSelectOptions}
      />
    </>
  );
};

const styles = {
  selectFull: { width: '100%' },
  timeStepQuestionMarkIcon: () => ({
    svg: { width: 12, height: 12 },
  }),
};
