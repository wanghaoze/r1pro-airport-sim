import LiveDownloads from './LiveDownloads';
import EnglishGuide from './EnglishGuide';
export default function Help(){return <section className="page-content help-page">
  <div className="eyebrow">SCENE STUDIO GUIDE</div><h1>Help & workstation setup</h1>
  <p>Follow the complete workflow: edit a scene, understand how qualified data enters training, train a model, track progress and evaluate registered rooms.</p>
  <EnglishGuide/>
  <details className="help-resources"><summary>Setup guides, source packages & reference recordings</summary>
    <div className="evaluation-card"><h2>Workstation and policy setup</h2><p>Model registration is separate from loading, inference and task success. Use these guides for compatible checkpoint metadata, gripper units, ROS 2 transport and workstation startup. Check the deployed release and existing process before starting another service.</p><div className="figure-downloads"><a className="button" href="/help/workstation.md" download>Download workstation & ROS 2 README</a><a className="button" href="/help/policy-evaluation.md" download>Download policy evaluation guide</a><a className="button" href="/help/USER_GUIDE_ZH.md" download>Download Chinese guide (.md)</a></div></div>
    <p>These recordings are reference material. For a new evaluation's own recordings, open Policy evaluation → Previous runs → This run's result & downloads.</p><LiveDownloads/>
  </details>
</section>;}
