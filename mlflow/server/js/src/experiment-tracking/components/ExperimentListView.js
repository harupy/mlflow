import React, { Component } from 'react';
import PropTypes from 'prop-types';
import { connect } from 'react-redux';
import { Input, Tree } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import './ExperimentListView.css';
import { getExperiments } from '../reducers/Reducers';
import { Experiment } from '../sdk/MlflowMessages';
import Routes from '../routes';
import { Link } from 'react-router-dom';
import { CreateExperimentModal } from './modals/CreateExperimentModal';
import { DeleteExperimentModal } from './modals/DeleteExperimentModal';
import { RenameExperimentModal } from './modals/RenameExperimentModal';
import { IconButton } from '../../common/components/IconButton';
import Utils from '../../common/utils/Utils';
import { withRouter } from 'react-router-dom';

export class ExperimentListView extends Component {
  static propTypes = {
    onClickListExperiments: PropTypes.func.isRequired,
    activeExperimentIds: PropTypes.arrayOf(PropTypes.string),
    experiments: PropTypes.arrayOf(Experiment).isRequired,
  };

  state = {
    height: undefined,
    searchInput: '',
    showCreateExperimentModal: false,
    showDeleteExperimentModal: false,
    showRenameExperimentModal: false,
    selectedExperimentId: '0',
    selectedExperimentName: '',
  };

  componentDidMount() {
    this.resizeListener = () => {
      this.setState({ height: window.innerHeight });
    };
    window.addEventListener('resize', this.resizeListener);
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.resizeListener);
  }

  handleSearchInputChange = (event) => {
    this.setState({ searchInput: event.target.value });
  };

  preventDefault = (ev) => ev.preventDefault();

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

  handleDeleteExperiment = (ev) => {
    this.setState({
      showDeleteExperimentModal: true,
    });

    const data = ev.currentTarget.dataset;
    this.updateSelectedExperiment(data.experimentid, data.experimentname);
  };

  handleRenameExperiment = (ev) => {
    this.setState({
      showRenameExperimentModal: true,
    });

    const data = ev.currentTarget.dataset;
    this.updateSelectedExperiment(data.experimentid, data.experimentname);
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

  getFilteredActiveExperimentIds = () => {
    const { experiments, activeExperimentIds } = this.props;
    const { searchInput } = this.state;

    if (activeExperimentIds === undefined) {
      return [];
    }
    if (experiments === undefined || searchInput === undefined || searchInput === '') {
      return activeExperimentIds;
    }
    const filteredExperimentIds = experiments
      .filter(({ name }) => name.toLowerCase().includes(searchInput.toLowerCase()))
      .map(({ experiment_id }) => experiment_id);

    return activeExperimentIds.filter((exp_id) => filteredExperimentIds.includes(exp_id));
  };

  getCompareExperimentsPageRoute = (experimentId) => {
    // Make a copy to avoid modifying the props
    const activeIds = [...this.getFilteredActiveExperimentIds()];
    const index = activeIds.indexOf(experimentId);
    if (index > -1) {
      activeIds.splice(index, 1);
    } else {
      activeIds.push(experimentId);
    }
    // Route to a currently selected experiment if there are no active ones
    if (activeIds.length === 0) {
      return Routes.getExperimentPageRoute(this.state.selectedExperimentId);
    }
    return Routes.getCompareExperimentsPageRoute(activeIds);
  };

  onSelect = (_selectedKeys, event) => {
    const { key } = event.node;
    const activeIds = this.getFilteredActiveExperimentIds();
    if (activeIds.length === 1 && activeIds[0] === key) {
      return;
    }

    const route = Routes.getExperimentPageRoute(key);
    this.props.history.push(route);
  };

  onCheck = (_selectedKeys, event) => {
    const { key } = event.node;
    const activeIds = this.getFilteredActiveExperimentIds();
    if (activeIds.length === 1 && activeIds[0] === key) {
      return;
    }
    const route = this.getCompareExperimentsPageRoute(key);
    this.props.history.push(route);
  };

  render() {
    const height = this.state.height || window.innerHeight;
    // 60 pixels for the height of the top bar.
    // 100 for the experiments header and some for bottom padding.
    const experimentListHeight = height - 60 - 100;
    // get searchInput from state
    const { searchInput } = this.state;
    const { experiments, activeExperimentIds } = this.props;
    const filteredExperiments = experiments
      // filter experiments based on searchInput
      .filter((exp) =>
        exp
          .getName()
          .toLowerCase()
          .includes(searchInput.toLowerCase()),
      );
    const treeData = filteredExperiments.map(({ name, experiment_id }) => ({
      title: name,
      key: experiment_id,
    }));

    const titleRender = ({ title, key }) => (
      <div style={{ display: 'flex', alignItems: 'center', height: '32px' }}>
        <div style={{ width: '80%' }}>{title}</div>
        {this.props.activeExperimentIds?.length == 1 && (
          <>
            <IconButton
              icon={<EditOutlined />}
              onClick={this.handleRenameExperiment}
              data-experimentid={key}
              data-experimentname={title}
              style={{ marginRight: 10 }}
            />
            {/* Delete Experiment option */}
            <IconButton
              icon={<i className='far fa-trash-alt' />}
              onClick={this.handleDeleteExperiment}
              data-experimentid={key}
              data-experimentname={title}
              style={{ marginRight: 10 }}
            />
          </>
        )}
      </div>
    );

    return (
      <div className='experiment-list-outer-container'>
        <CreateExperimentModal
          isOpen={this.state.showCreateExperimentModal}
          onClose={this.handleCloseCreateExperimentModal}
        />
        <DeleteExperimentModal
          isOpen={this.state.showDeleteExperimentModal}
          onClose={this.handleCloseDeleteExperimentModal}
          activeExperimentIds={this.props.activeExperimentIds}
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
            className='experiment-list-search-input'
            type='text'
            placeholder='Search Experiments'
            aria-label='search experiments'
            value={searchInput}
            onChange={this.handleSearchInputChange}
          />
          <div className='experiment-list-container' style={{ height: experimentListHeight }}>
            <Tree
              checkable
              selectable
              blockNode
              treeData={treeData}
              titleRender={titleRender}
              checkedKeys={activeExperimentIds}
              onSelect={this.onSelect}
              onCheck={this.onCheck}
            />
          </div>
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state) => {
  const experiments = getExperiments(state);
  experiments.sort(Utils.compareExperiments);
  return { experiments };
};

export default withRouter(connect(mapStateToProps)(ExperimentListView));
