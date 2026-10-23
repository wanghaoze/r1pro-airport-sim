import {useMemo, useState} from 'react';
import guide from '@/lib/english-guide.json';

function Inline({text}:{text:string}) {
  return <>{text.split(/(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s]+)/g).map((part,i)=>
    part.startsWith('**')?<strong key={i}>{part.slice(2,-2)}</strong>:
    part.startsWith('`')?<code key={i}>{part.slice(1,-1)}</code>:
    /^https?:\/\//.test(part)?<a key={i} href={part} target="_blank" rel="noreferrer">{part}</a>:part)}</>;
}

function Content({text}:{text:string}) {
  const lines=text.trim().split('\n'),blocks=[];
  for(let i=0;i<lines.length;){
    const line=lines[i];
    if(!line.trim()){i++;continue;}
    if(line.startsWith('```')){
      const code=[];i++;while(i<lines.length&&!lines[i].startsWith('```'))code.push(lines[i++]);i++;
      blocks.push(<pre key={blocks.length}>{code.join('\n')}</pre>);continue;
    }
    if(line.startsWith('### ')){blocks.push(<h3 key={blocks.length}>{line.slice(4)}</h3>);i++;continue;}
    if(line.startsWith('|')){
      const rows:string[][]=[];
      while(i<lines.length&&lines[i].startsWith('|')){
        const row=lines[i++].split('|').slice(1,-1).map(x=>x.trim());
        if(!row.every(x=>/^:?-+:?$/.test(x)))rows.push(row);
      }
      blocks.push(<div className="guide-table" key={blocks.length}><table><thead><tr>{rows[0]?.map((cell,k)=><th key={k}><Inline text={cell}/></th>)}</tr></thead><tbody>{rows.slice(1).map((row,k)=><tr key={k}>{row.map((cell,j)=><td key={j}><Inline text={cell}/></td>)}</tr>)}</tbody></table></div>);continue;
    }
    if(/^(\d+\. |- )/.test(line)){
      const ordered=/^\d+\./.test(line),items=[];
      const pattern=ordered?/^\d+\. /:/^- /;
      while(i<lines.length&&pattern.test(lines[i]))items.push(lines[i++].replace(pattern,''));
      const children=items.map((item,k)=><li key={k}><Inline text={item}/></li>);
      blocks.push(ordered?<ol key={blocks.length}>{children}</ol>:<ul key={blocks.length}>{children}</ul>);continue;
    }
    const paragraph=[lines[i++]];
    while(i<lines.length&&lines[i].trim()&&!/^(### |```|\||\d+\. |- )/.test(lines[i]))paragraph.push(lines[i++]);
    blocks.push(<p key={blocks.length}><Inline text={paragraph.join(' ')}/></p>);
  }
  return <>{blocks}</>;
}

const parts=guide.text.split(/^## /m);
const intro=parts[0].replace(/^# .+\n/, '');
const chapters=parts.slice(1).map((part,index)=>({index,title:part.split('\n')[0],body:part.slice(part.indexOf('\n')+1)}));

export default function EnglishGuide(){
  const [query,setQuery]=useState(''),[selected,setSelected]=useState(0),[all,setAll]=useState(false);
  const matches=useMemo(()=>chapters.filter(c=>(c.title+' '+c.body).toLowerCase().includes(query.trim().toLowerCase())),[query]);
  const shown=query.trim()?matches:all?chapters:[chapters[selected]];
  function choose(index:number){setSelected(index);setQuery('');setAll(false);document.getElementById('guide-reader')?.scrollIntoView({block:'start',behavior:'smooth'});}
  return <section className="english-guide" aria-label="Complete English user guide">
    <div className="guide-intro"><h2>Complete English user guide</h2><Content text={intro}/></div>
    <div className="guide-controls"><label htmlFor="guide-search">Search the guide<input id="guide-search" className="field" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Try dataset, checkpoint, stop reason…"/></label><label className="guide-all"><input type="checkbox" checked={all} onChange={e=>setAll(e.target.checked)}/> Show all chapters</label><a className="button" href="/help/USER_GUIDE_EN.md" download>Download English guide (.md)</a></div>
    <div className="guide-layout"><nav className="guide-toc" aria-label="Guide chapters">{matches.map(c=><button key={c.index} aria-current={!all&&!query&&selected===c.index?'location':undefined} onClick={()=>choose(c.index)}>{c.title}</button>)}</nav><div id="guide-reader" className="guide-reader" aria-live="polite">{query.trim()&&<p role="status">{matches.length} matching chapters</p>}{!shown.length&&<p>No matching chapters. Try “scene”, “training” or “MSE”.</p>}{shown.map(c=><article key={c.index}><h2>{c.title}</h2><Content text={c.body}/></article>)}{!query&&!all&&<div className="guide-pagination"><button className="button" disabled={selected===0} onClick={()=>choose(selected-1)}>Previous chapter</button><span>{selected+1} / {chapters.length}</span><button className="button" disabled={selected===chapters.length-1} onClick={()=>choose(selected+1)}>Next chapter</button></div>}</div></div>
  </section>;
}
