"use client";
import {Component,type ReactNode} from 'react';
export default class PanelBoundary extends Component<{children:ReactNode},{failed:boolean}>{
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  render(){return this.state.failed?<section className="page-content" role="alert"><h2>This panel could not display a report</h2><p>Your jobs continue on the server. Try loading the latest snapshot.</p><button className="button" onClick={()=>this.setState({failed:false})}>Retry panel</button></section>:this.props.children;}
}
