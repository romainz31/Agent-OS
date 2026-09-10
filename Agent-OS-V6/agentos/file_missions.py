"""Connect document jobs to native M-xxx missions and Mission Control."""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from agentos.file_assistant import FileAssistant, FileCollision, file_signature, TEXT, JOB_REF, TTL, now, norm


class DocumentCancelled(RuntimeError):
    pass


class MissionFileAssistant(FileAssistant):
    def __init__(self, runtime):
        from agentos.config import WORKSPACE_DIR, DATA_DIR
        self.runtime = runtime
        self.manager = runtime.manager
        self.local = threading.local()
        self.controls = threading.Condition(threading.RLock())
        self.paused = set()
        self.cancelled = set()
        self.active = set()
        self.started = set()
        self.mapping = {}
        self.aliases = {}
        self.expiry_stop = threading.Event()
        super().__init__(self.manager.llm, WORKSPACE_DIR, DATA_DIR,
                         getattr(self.manager, '_append_notification', None))
        self.restore()
        self.bind_controls()
        self.expiry_thread = threading.Thread(target=self.expiry_loop, daemon=True, name='document-approvals')
        self.expiry_thread.start()

    def mission(self, jid):
        return self.manager.missions.resolve(jid)

    def new_id(self, kind, details, description):
        title = {'create': 'Création de fichier', 'analyse': 'Analyse de documents',
                 'sort': 'Classement de documents', 'export': 'Export des informations'}.get(kind, 'Documents')
        if details.get('path'):
            title += ' — ' + str(details['path']).replace('\\', '/').rstrip('/').split('/')[-1]
        mission = self.manager.missions.create(title=title, description=description, metadata={
            'document_job': True, 'autonomy_enabled': False,
            'document_request': {'kind': kind, 'details': details, 'description': description}})
        self.attach_task(mission)
        return mission.human_id

    def attach_task(self, mission):
        task = next((self.manager.tasks.get(t) for t in mission.task_ids if self.manager.tasks.get(t)), None)
        if task is None:
            task = self.manager.tasks.create(title=mission.title, description=mission.description, worker='documents',
                metadata={'mission_id': mission.id, 'document_job': True, 'auto_repair_enabled': False})
            self.manager.missions.attach_plan(mission.id, plan=[{'title': mission.title, 'worker': 'documents'}], task_ids=[task.id])
        self.mapping[mission.human_id] = task.id
        return task

    def restore(self):
        # All previous live approvals were invalidated by FileAssistant.__init__.
        # Reuse metadata to make migration restartable without duplicating missions.
        for m in self.manager.missions.list():
            if m.metadata.get('document_job'):
                self.attach_task(m)
                if m.metadata.get('legacy_file_job'):
                    self.aliases[m.metadata['legacy_file_job']] = m.human_id
        with self.connect() as c:
            rows = c.execute('SELECT id,status,detail,created FROM jobs ORDER BY created').fetchall()
        for old, status, detail, created in rows:
            jid = old
            if old.startswith('F-'):
                jid = self.aliases.get(old)
                if not jid:
                    m = self.manager.missions.create(title='Documents — travail antérieur', description=detail,
                        metadata={'document_job': True, 'autonomy_enabled': False, 'legacy_file_job': old})
                    self.attach_task(m)
                    jid = m.human_id
                    self.aliases[old] = jid
                with self.connect() as c:
                    c.execute('UPDATE jobs SET id=? WHERE id=?', (jid, old))
                    c.execute('UPDATE documents SET job=? WHERE job=?', (jid, old))
            if jid not in self.mapping:
                # A foreign/missing mission should not be guessed or overwrite another mission.
                raise RuntimeError('Mission documentaire absente pour ' + jid)
            if status in {'en pause', 'en cours', 'en attente', 'autorisation requise'}:
                status, detail = 'interrompu', detail + '\nRedémarrage : nouvelle autorisation nécessaire.'
            self.job(jid, status, self.translate(detail))
        with self.connect() as c:
            for jid, detail in c.execute('SELECT id,detail FROM jobs').fetchall():
                translated = self.translate(detail)
                c.execute('UPDATE jobs SET detail=? WHERE id=?', (translated, jid))
        # Recover a crash between creating the native mission and creating the SQLite job.
        with self.connect() as c:
            present = {r[0] for r in c.execute('SELECT id FROM jobs')}
        for jid in self.mapping:
            if jid not in present:
                self.job(jid, 'interrompu', 'Création interrompue. Relancer la mission pour demander une nouvelle autorisation.')

    def translate(self, message):
        def sub(m):
            ref = m[0].upper()
            if ref.startswith('M-'):
                return f'M-{int(ref[2:]):03d}'
            return self.aliases.get(ref, ref)
        return re.sub(JOB_REF, sub, str(message), flags=re.I)

    def job(self, jid, status, detail):
        super().job(jid, status, detail)
        tid = self.mapping.get(jid)
        if not tid:
            return
        statuses = {'en attente': 'pending', 'en cours': 'running', 'autorisation requise': 'waiting_approval',
                    'en pause': 'paused', 'terminé': 'completed', 'échec': 'failed', 'interrompu': 'failed',
                    'expiré': 'failed', 'refusé': 'cancelled', 'annulé': 'cancelled'}
        data = {'document_job': True, 'document_result': detail}
        if status == 'autorisation requise':
            data['approval_required_files'] = detail.splitlines()
        if status == 'refusé':
            data['approval_status'] = 'rejected'
        self.manager.tasks.update(tid, status=statuses[status], result=detail, result_data=data,
                                  error=detail if status in {'échec','interrompu','expiré'} else None)
        mission = self.mission(jid)
        self.manager.missions.refresh(mission, self.manager.tasks)

    def checkpoint(self):
        jid = getattr(self.local, 'jid', None)
        with self.controls:
            while jid in self.paused and not self.stopping.is_set() and jid not in self.cancelled:
                self.controls.wait(timeout=0.5)
            if self.stopping.is_set() or jid in self.cancelled:
                raise DocumentCancelled('Opération arrêtée ; les fichiers déjà créés sont conservés.')

    def submit(self, jid, action):
        with self.controls:
            if jid in self.active:
                return jid + ' est déjà en cours.'
            self.active.add(jid)
            self.cancelled.discard(jid)
            self.paused.discard(jid)
        self.manager.missions.set_control_status(self.mission(jid).id, None)
        self.job(jid, 'en attente', 'Mission autorisée, en file de travail.')
        def run():
            self.local.jid = jid
            try:
                self.checkpoint()
                with self.controls:
                    self.started.add(jid)
                self.job(jid, 'en cours', 'Traitement documentaire en cours.')
                result = action()
                self.checkpoint()
                self.job(jid, 'terminé', result)
            except FileCollision as exc:
                try:
                    self.checkpoint()
                    result = self.collision_request(jid, exc.details)
                except DocumentCancelled as stopped:
                    result = str(stopped)
                    self.job(jid, 'interrompu' if self.stopping.is_set() else 'annulé', result)
                except Exception as failed:
                    result = 'Échec : ' + str(failed)
                    self.job(jid, 'échec', result)
            except DocumentCancelled as exc:
                result = str(exc)
                self.job(jid, 'interrompu' if self.stopping.is_set() else 'annulé', result)
            except Exception as exc:
                result = 'Échec : ' + str(exc)
                self.job(jid, 'échec', result)
            finally:
                with self.controls:
                    self.active.discard(jid)
                    self.started.discard(jid)
                    self.controls.notify_all()
                self.local.jid = None
            try:
                self.notify(f'{jid} : {result[:1800]}\nDétail dans Mission Control ou : fichiers resultat {jid}')
            except Exception:
                pass
        self.futures = [f for f in self.futures if not f.done()]
        self.futures.append(self.pool.submit(run))
        return f'Mission {jid} lancée en arrière-plan. Suivi dans Mission Control.\nDétail : fichiers resultat {jid}'

    def expiry_loop(self):
        while not self.expiry_stop.wait(1):
            with self.lock:
                expired = [j for j, (exp, _, _) in self.pending.items() if time.monotonic() > exp]
                for j in expired:
                    self.pending.pop(j, None)
                    self.job(j, 'expiré', 'Autorisation expirée. Relance la mission pour demander un nouvel accord.')

    def control(self, mission, action):
        jid = mission.human_id
        with self.controls:
            if action == 'cancel':
                if mission.status == 'completed':
                    return jid + ' est déjà terminée.'
                self.cancelled.add(jid)
                self.paused.discard(jid)
                with self.lock:
                    self.pending.pop(jid, None)
                self.manager.missions.set_control_status(mission.id, 'cancelled')
                self.job(jid, 'annulé', 'Annulée. Les fichiers déjà créés restent en place ; arrêt au prochain point de contrôle.')
                self.controls.notify_all()
                return jid + ' annulée. Les fichiers déjà créés sont conservés.'
            if action == 'pause':
                if jid not in self.active:
                    return jid + ' : aucune exécution à suspendre. Une autorisation en attente reste nécessaire.'
                self.paused.add(jid)
                self.manager.missions.set_control_status(mission.id, 'paused')
                self.job(jid, 'en pause', 'Pause demandée. Le calcul en cours peut finir, puis arrêt avant la prochaine lecture/écriture.')
                return jid + ' mise en pause au prochain point de contrôle.'
            if action == 'resume':
                if jid not in self.paused:
                    return jid + " n'est pas en pause."
                self.paused.remove(jid)
                self.manager.missions.set_control_status(mission.id, None)
                self.job(jid, 'en cours' if jid in self.started else 'en attente', 'Reprise du traitement autorisé.')
                self.controls.notify_all()
                return jid + ' reprise.'
            if action == 'retry':
                if jid in self.active:
                    return 'Attends la fin du calcul en cours de ' + jid + ' avant de relancer.'
                if mission.status not in {'failed','cancelled','rejected'}:
                    return jid + " n'est pas à relancer."
                request = mission.metadata.get('document_request')
                if not request:
                    return 'Ancien travail importé : renvoie ta demande initiale pour créer une nouvelle mission autorisée.'
                if request['kind'] == 'create' and Path(request['details']['path']).exists():
                    self.cancelled.discard(jid)
                    self.paused.discard(jid)
                    self.manager.missions.set_control_status(mission.id, None)
                    return self.collision_request(jid, request['details'])
                # Even creation retries request fresh consent; previous consent is never reusable.
                self.cancelled.discard(jid)
                self.paused.discard(jid)
                self.manager.missions.set_control_status(mission.id, None)
                with self.lock:
                    self.pending[jid] = (time.monotonic() + TTL, request['kind'], request['details'])
                description = request['description'] + '\nNouvelle autorisation nécessaire pour cette relance.'
                self.job(jid, 'autorisation requise', description)
                return description + f'\nAutorise {jid} dans Mission Control ou : fichiers autoriser {jid}'
        raise ValueError('Action inconnue.')

    def collision_request(self, jid, details):
        # This stores no overwrite permission in persistent mission metadata.
        path = Path(details['path'])
        signature = file_signature(path)
        description = (
            f'Le fichier « {path} » existe déjà. Que souhaites-tu faire ?\n'
            f'1. Créer le nouveau fichier sous un autre nom : fichiers renommer {jid} "nouveau_nom{path.suffix}"\n'
            f'2. ÉCRASER le fichier existant : fichiers ecraser {jid}\n'
            'Dans Mission Control, le bouton Autoriser signifie ÉCRASER ce fichier. '
            'Le bouton Refuser conserve le fichier et refuse la création.\n'
            'Le renommage concerne le nouveau fichier à créer ; le fichier existant reste en place. '
            'Choix valable 15 minutes pour cette version du fichier uniquement.'
        )
        pending_details = {'creation': dict(details), 'signature': signature}
        with self.controls:
            if jid in self.cancelled or self.stopping.is_set():
                raise DocumentCancelled('Mission arrêtée. Fichier existant conservé.')
            with self.lock:
                self.pending[jid] = (time.monotonic() + TTL, 'collision', pending_details)
            self.job(jid, 'autorisation requise', description)
        return description

    def collision_choice(self, jid, *, rename=None):
        # Always acquire controls before the consent lock, as control() does.
        with self.controls:
            with self.lock:
                pending = self.pending.get(jid)
                if not pending or pending[1] != 'collision':
                    return 'Aucun choix renommer/écraser en attente pour ' + jid + '.'
                if time.monotonic() > pending[0]:
                    self.pending.pop(jid)
                    self.job(jid, 'expiré', 'Choix expiré. Relance la mission pour choisir à nouveau.')
                    return 'Choix expiré. Relance ' + jid + '.'
                if jid in self.active:
                    return 'La mission prépare le choix. Réessaie dans un instant.'
                details = dict(pending[2]['creation'])
                if rename is not None:
                    name = rename.strip()
                    if (not name or name in {'.', '..'} or any(c in name for c in '/\\<>:"|?*')
                            or name.endswith(('.', ' ')) or any(ord(c) < 32 for c in name)):
                        return 'Indique un simple nom de fichier, sans chemin ni caractères interdits.'
                    if Path(name).suffix.lower() not in TEXT | {'.pdf', '.docx', '.xlsx'}:
                        return 'Format non pris en charge. Choisis par exemple TXT, MD, JSON, DOCX, PDF ou XLSX.'
                    old_path = details['path']
                    details['path'] = str(Path(old_path).with_name(name))
                    details['objective'] = (details['objective'] + '\nDestination finale demandée par l’utilisateur : '
                                            + name + '. Utilise ce nom et son format, même si la demande initiale cite un autre nom.')
                    mission = self.mission(jid)
                    request = {'kind': 'create', 'details': details, 'description': 'Créer ' + details['path']}
                    self.manager.missions.set_status(mission.id, mission.status, metadata_patch={'document_request': request})
                    with self.manager.missions.lock:
                        mission.title = 'Création de fichier — ' + name
                        mission.description = request['description']
                        self.manager.missions._save()
                    self.manager.tasks.update(self.mapping[jid], title=mission.title, description=mission.description)
                else:
                    # This grant exists only in the consumed callback, never on a retry.
                    details['overwrite_signature'] = pending[2]['signature']
                self.pending.pop(jid)
            return self.submit(jid, lambda: self.create(details))

    def handle(self, message):
        value = self.translate(message)
        renamed = re.fullmatch(r'fichiers renommer (M-\d+) ["«]([^"»]+)["»]', value, re.I)
        if renamed:
            return self.collision_choice(renamed[1].upper(), rename=renamed[2])
        overwrite = re.fullmatch(r'fichiers (?:ecraser|écraser|autoriser) (M-\d+)', value, re.I)
        if overwrite:
            jid = overwrite[1].upper()
            with self.lock:
                choice = self.pending.get(jid)
            if choice and choice[1] == 'collision':
                return self.collision_choice(jid)
            if norm(value).startswith('fichiers ecraser '):
                return 'Aucun écrasement en attente pour ' + jid + '. Relance la mission si nécessaire.'
        # Export is also a real native mission (only already-approved saved data).
        m = re.fullmatch(r'fichiers exporter (M-\d+)', value, re.I)
        if m:
            source = m[1].upper()
            jid = self.new_id('export', {'source': source}, 'Exporter les informations de ' + source)
            return self.submit(jid, lambda: self.export(source))
        # Base class maps non-create approvals to sort; export retry is handled explicitly.
        m = re.fullmatch(r'fichiers autoriser (M-\d+)', value, re.I)
        if m:
            jid = m[1].upper()
            with self.lock:
                p = self.pending.get(jid)
                approved_export = bool(p and p[1] == 'export' and time.monotonic() <= p[0])
                if approved_export:
                    self.pending.pop(jid)
            if approved_export:
                return self.submit(jid, lambda: self.export(p[2]['source']))
        return super().handle(value)

    def bind_controls(self):
        service = self
        # The existing Web API and conversational controls both use these objects.
        for action in ('pause', 'resume', 'cancel', 'retry'):
            original = getattr(self.runtime.control, action)
            def handler(mission, _action=action, _original=original):
                if mission.metadata.get('document_job'):
                    return service.control(mission, _action)
                return _original(mission)
            setattr(self.runtime.control, action, handler)
        for action, command in (('approve_task','autoriser'), ('reject_task','refuser')):
            original = getattr(self.manager.approvals, action)
            def approval(task_id, _command=command, _original=original):
                task = service.manager.tasks.get(task_id)
                if task and task.metadata.get('document_job'):
                    mission = service.manager.missions.get(task.metadata['mission_id'])
                    return service.handle(f'fichiers {_command} {mission.human_id}')
                return _original(task_id)
            setattr(self.manager.approvals, action, approval)
        original_submit = self.manager.engine.submit
        def submit(task_id):
            task = service.manager.tasks.get(task_id)
            if task and task.metadata.get('document_job'):
                return False  # only the document executor owns consent and execution
            return original_submit(task_id)
        self.manager.engine.submit = submit
        original_check = self.runtime.autonomy._check_tasks
        def check(mission):
            if mission.metadata.get('document_job'):
                return {'submitted': 0, 'orphan_recovered': 0, 'approval_reminders': 0}
            return original_check(mission)
        self.runtime.autonomy._check_tasks = check

    def close(self):
        self.expiry_stop.set()
        self.expiry_thread.join(timeout=2)
        self.stopping.set()
        with self.controls:
            self.controls.notify_all()
        super().close()


def install_file_missions(runtime):
    if isinstance(getattr(runtime, 'file_assistant', None), MissionFileAssistant):
        return
    runtime.file_assistant = MissionFileAssistant(runtime)
