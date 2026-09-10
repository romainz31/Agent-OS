(() => {
  const panel=document.createElement('section');
  panel.style.cssText='display:none;position:fixed;inset:80px 16px 16px;max-width:1000px;margin:auto;padding:24px;border:1px solid #52627a;border-radius:16px;background:#111827;color:#e5e7eb;z-index:2000;overflow:auto;box-shadow:0 0 0 100vmax #0008';
  panel.setAttribute('role','dialog');
  panel.setAttribute('aria-label','Timeline personnelle');
  panel.innerHTML=`<button id="lifeClose" style="float:right">Fermer</button><h2>Paul · Ma Timeline</h2>
  <p>Un seul endroit pour ce que tu dois faire, tes rendez-vous, les événements et ce que tu as réellement fait.</p>
  <button id="lifeRefresh">Voir aujourd'hui</button>
  <pre id="lifeToday" style="white-space:pre-wrap"></pre>
  <details><summary>Rechercher dans ma Timeline</summary>
  <p>Choisis une période et écris éventuellement un mot, par exemple « piscine » ou « dentiste ».</p>
  <label>Du <input id="lifeStart" type="date"></label> <label>au <input id="lifeEnd" type="date"></label>
  <input id="lifeQuery" placeholder="Exemple : piscine"><button id="lifeSearch">Rechercher</button>
  <pre id="lifeHistory" style="white-space:pre-wrap"></pre></details>
  <h3>Donner un fichier à Paul</h3>
  <p>Choisis une image ou un document. La consigne est facultative : si tu la laisses vide, Paul te demandera quoi en faire dans la discussion.</p>
  <input id="lifeFiles" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv,.tsv,.docx,.xlsx,.json,.yaml,.yml">
  <input id="lifeObjective" style="width:55%" placeholder="Facultatif : ce que Paul doit faire avec le fichier">
  <button id="lifeUpload">Donner à Paul</button><pre id="lifeResult" style="white-space:pre-wrap"></pre>
  <button id="lifeExports">Voir les fichiers créés par Paul</button><div id="lifeLinks"></div>`;
  document.body.append(panel);

  const open=document.createElement('button');
  open.textContent='Ma Timeline';
  open.style.cssText='position:fixed;right:20px;bottom:20px;z-index:1500;padding:12px;border-radius:12px;background:#263d6b;color:white';
  document.body.append(open);
  open.onclick=()=>{panel.style.display='block';document.getElementById('lifeClose').focus();};
  document.getElementById('lifeClose').onclick=()=>{panel.style.display='none';open.focus();};
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){panel.style.display='none';}});

  const el=id=>document.getElementById(id);
  const request=async(url,options)=>{
    const res=await fetch(url,options);
    const data=await res.json();
    if(!res.ok)throw Error(data.detail||'Erreur serveur');
    return data;
  };
  const kindLabel={todo:'tâche',appointment:'rendez-vous',event:'événement',action:'fait',mood:'ressenti'};
  const statusLabel={pending:'à faire',done:'fait',logged:'noté',scheduled:'prévu'};

  el('lifeRefresh').onclick=async()=>{
    try{el('lifeToday').textContent=(await request('/api/timeline')).today;}
    catch(e){el('lifeToday').textContent=e.message;}
  };

  el('lifeSearch').onclick=async()=>{
    try{
      const params=new URLSearchParams({
        start:el('lifeStart').value||'1970-01-01',
        end:el('lifeEnd').value||'9999-12-31',
        q:el('lifeQuery').value
      });
      const d=await request('/api/timeline?'+params);
      const rows=d.timeline||[];
      const heading=rows.length===0?"Je n’ai rien retrouvé.":rows.length===1?"J’ai retrouvé une chose :":`J’ai retrouvé ${rows.length} choses :`;
      const lines=rows.map(row=>{
        const when=row.start_time?`${row.day} ${row.start_time}`:row.day;
        const type=kindLabel[row.kind]||row.kind;
        const status=((row.kind==='appointment'||row.kind==='event')&&row.status==='pending')?'prévu':(statusLabel[row.status]||row.status);
        return `${when} · ${type} · ${status} · ${row.title}`;
      });
      el('lifeHistory').textContent=heading+(rows.length?'\n'+lines.join('\n'):'');
    }catch(e){el('lifeHistory').textContent=e.message;}
  };

  el('lifeUpload').onclick=async()=>{
    el('lifeUpload').disabled=true;
    el('lifeResult').textContent='';
    try{
      const files=[...el('lifeFiles').files];
      const objective=el('lifeObjective').value.trim();
      if(!files.length)throw Error('Choisis d’abord une image ou un document.');
      if(!objective&&files.length>1)throw Error('Sans consigne, donne-moi un seul fichier à la fois pour que Paul puisse te demander quoi en faire.');
      for(const file of files){
        if(file.size>10*1024*1024)throw Error('10 Mio maximum par fichier');
        const body=new FormData();
        body.append('file',file);
        body.append('objective',objective);
        const data=await request('/api/documents/upload',{method:'POST',body});
        el('lifeResult').textContent+=`Paul : ${data.response}\n\n`;
        if(data.awaiting_instruction)el('lifeResult').textContent+='Réponds-lui maintenant dans la discussion principale.\n\n';
      }
    }catch(e){el('lifeResult').textContent+=e.message;}
    finally{el('lifeUpload').disabled=false;}
  };

  el('lifeExports').onclick=async()=>{
    try{
      const d=await request('/api/documents/exports');
      el('lifeLinks').replaceChildren();
      for(const f of d.files){
        const a=document.createElement('a');
        a.href=f.url;
        a.textContent=f.name;
        a.style.display='block';
        el('lifeLinks').append(a);
      }
    }catch(e){el('lifeLinks').textContent=e.message;}
  };
})();
