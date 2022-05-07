import React, { Component } from 'react';
import PropTypes from 'prop-types';
import { EditOutlined } from '@ant-design/icons';
import './ExperimentListView.css';
import { Experiment } from '../sdk/MlflowMessages';
import Routes from '../routes';
import { CreateExperimentModal } from './modals/CreateExperimentModal';
import { DeleteExperimentModal } from './modals/DeleteExperimentModal';
import { RenameExperimentModal } from './modals/RenameExperimentModal';
import { IconButton } from '../../common/components/IconButton';
import { withRouter } from 'react-router-dom';
import { Tree, Input } from '@databricks/design-system';
import _ from 'lodash';

export class ExperimentListView extends Component {
  static propTypes = {
    onClickListExperiments: PropTypes.func.isRequired,
    activeExperimentIds: PropTypes.arrayOf(PropTypes.string).isRequired,
    experiments: PropTypes.arrayOf(Experiment).isRequired,
  };

  state = {
    searchInput: '',
    showCreateExperimentModal: false,
    showDeleteExperimentModal: false,
    showRenameExperimentModal: false,
    selectedExperimentId: '0',
    selectedExperimentName: '',
  };

  handleSearchInputChange = (event) => {
    this.setState({ searchInput: event.target.value });
  };

  updateSelectedExperiment = (experimentId, experimentName) => {
    this.setState({
      selectedExperimentId: experimentId,
      selectedExperimentName: experimentName,
    });
  };

  handleCreateExperiment = () => {
    this.setState({
      showCreateExperimentModal: true,
    });
  };

  handleDeleteExperiment = (experimentId, experimentName) => () => {
    this.setState({
      showDeleteExperimentModal: true,
    });
    this.updateSelectedExperiment(experimentId, experimentName);
  };

  handleRenameExperiment = (experimentId, experimentName) => () => {
    this.setState({
      showRenameExperimentModal: true,
    });
    this.updateSelectedExperiment(experimentId, experimentName);
  };

  handleCloseCreateExperimentModal = () => {
    this.setState({
      showCreateExperimentModal: false,
    });
  };

  handleCloseDeleteExperimentModal = () => {
    this.setState({
      showDeleteExperimentModal: false,
    });
    // reset
    this.updateSelectedExperiment('0', '');
  };

  handleCloseRenameExperimentModal = () => {
    this.setState({
      showRenameExperimentModal: false,
    });
    // reset
    this.updateSelectedExperiment('0', '');
  };

  getCompareExperimentsPageRoute = (experimentId, checked) => {
    const { activeExperimentIds } = this.props;
    const activeIds = checked
      ? [...activeExperimentIds, experimentId]
      : activeExperimentIds.filter((expId) => expId !== experimentId);

    if (activeIds.length === 1) {
      return Routes.getExperimentPageRoute(activeIds[0]);
    }
    return Routes.getCompareExperimentsPageRoute(activeIds.sort());
  };

  onSelect = (experimentId) => () => {
    const { activeExperimentIds } = this.props;
    if (_.isEqual(activeExperimentIds, [experimentId])) {
      return;
    }
    const route = Routes.getExperimentPageRoute(experimentId);
    this.props.history.push(route);
  };

  onCheck = (_checkedKeys, event) => {
    const {
      node: { key: experimentId },
      checked,
    } = event;
    const { activeExperimentIds } = this.props;
    if (_.isEqual(activeExperimentIds, [experimentId])) {
      return;
    }
    const route = this.getCompareExperimentsPageRoute(experimentId, checked);
    this.props.history.push(route);
  };

  renderListItem = ({ title, key }) => {
    const disabled = this.props.activeExperimentIds.length > 1;
    return (
      <div style={{ display: 'flex' }}>
        <div
          style={{
            width: '140px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          onClick={this.onSelect(key)}
        >
          {title}
        </div>
        <IconButton
          icon={<EditOutlined />}
          onClick={this.handleRenameExperiment(key, title)}
          disabled={disabled}
          style={{ marginRight: 5 }}
        />
        <IconButton
          icon={<i className='far fa-trash-alt' />}
          onClick={this.handleDeleteExperiment(key, title)}
          disabled={disabled}
          style={{ marginRight: 5 }}
        />
      </div>
    );
  };

  render() {
    const { searchInput } = this.state;
    const { experiments, activeExperimentIds } = this.props;
    const lowerCasedSearchInput = searchInput.toLowerCase();
    const filteredExperiments = experiments.filter(({ name }) =>
      name.toLowerCase().includes(lowerCasedSearchInput),
    );
    const treeData = filteredExperiments.map(({ name, experiment_id }) => ({
      title: name,
      key: experiment_id,
    }));

    return (
      <div className='experiment-list-outer-container'>
        <CreateExperimentModal
          isOpen={this.state.showCreateExperimentModal}
          onClose={this.handleCloseCreateExperimentModal}
        />
        <DeleteExperimentModal
          isOpen={this.state.showDeleteExperimentModal}
          onClose={this.handleCloseDeleteExperimentModal}
          activeExperimentId={activeExperimentIds[0]}
          experimentId={this.state.selectedExperimentId}
          experimentName={this.state.selectedExperimentName}
        />
        <RenameExperimentModal
          isOpen={this.state.showRenameExperimentModal}
          onClose={this.handleCloseRenameExperimentModal}
          experimentId={this.state.selectedExperimentId}
          experimentName={this.state.selectedExperimentName}
        />
        <div>
          <h1 className='experiments-header'>Experiments</h1>
          <div className='experiment-list-create-btn-container'>
            <i
              onClick={this.handleCreateExperiment}
              title='New Experiment'
              className='fas fa-plus fa-border experiment-list-create-btn'
            />
          </div>
          <div className='collapser-container'>
            <i
              onClick={this.props.onClickListExperiments}
              title='Hide experiment list'
              className='collapser fa fa-chevron-left login-icon'
            />
          </div>
          <Input
            placeholder='Search Experiments'
            aria-label='search experiments'
            value={searchInput}
            onChange={this.handleSearchInputChange}
          />
          <div className='experiment-list-container'>
            <Tree
              treeData={treeData}
              dangerouslySetAntdProps={{
                checkable: true,
                selectable: true,
                multiple: true,
                onCheck: this.onCheck,
                checkedKeys: activeExperimentIds,
                selectedKeys: activeExperimentIds,
                titleRender: this.renderListItem,
              }}
            />
          </div>
        </div>
      </div>
    );
  }
}

export default withRouter(ExperimentListView);
