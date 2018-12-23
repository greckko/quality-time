import React, { Component } from 'react';
import Measurement from './Measurement.js';


class Metric extends Component {
  constructor(props) {
    super(props);
    this.state = {measurement: null, metric: null, source: null}
  }
  componentDidMount() {
    let self = this;
    fetch('http://localhost:8080/' + this.props.metric)
      .then(function(response) {
        return response.json();
      })
      .then(function(json) {
        self.setState({measurement: json.measurement, metric: json.metric, source: json.source});
      });
  }
  render() {
    const m = this.state.metric;
    if (m === null) {return null};
    const search = this.props.search_string;
    if (search && !m.name.toLowerCase().includes(search.toLowerCase())) {return null};
    return (
      <Measurement measurement={this.state.measurement} metric={this.state.metric} source={this.state.source} />
    )
  }
}

export default Metric;