"""Durable dated observations; agenda remains the sole task store."""
from __future__ import annotations
import calendar
import json
import re
import unicodedata
from datetime import date, timedelta


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s.lower()) if not unicodedata.combining(c))


class LifeJournal:
    def __init__(self, agenda):
        self.agenda = agenda
        with agenda._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS life_events(
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, title TEXT NOT NULL,
                kind TEXT NOT NULL, source TEXT NOT NULL, created TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS life_day ON life_events(day,kind)')
            db.execute('CREATE TABLE IF NOT EXISTS life_notices(key TEXT PRIMARY KEY)')

    def add(self, title, day, kind='action', source=''):
        date.fromisoformat(day)
        if kind not in ('action', 'humeur'): raise ValueError('Type inconnu')
        title = title.strip()
        if not title: raise ValueError('Action vide')
        with self.agenda._connect() as db:
            # Repeated reports on the same day are not silently counted twice.
            old = db.execute('SELECT id FROM life_events WHERE day=? AND title=? AND kind=?', (day,title,kind)).fetchone()
            if old: return old[0], False
            cur = db.execute('INSERT INTO life_events(day,title,kind,source,created) VALUES(?,?,?,?,?)',
                (day,title,kind,source,self.agenda._now().isoformat()))
            return cur.lastrowid, True

    @staticmethod
    def _natural_list(values):
        values = [str(value).strip() for value in values if str(value).strip()]
        if len(values) < 2:
            return values[0] if values else ''
        return ', '.join(values[:-1]) + ' et ' + values[-1]

    @staticmethod
    def _as_user_action(value):
        value = str(value).strip(' .')
        value = re.sub(r"^j[’']ai\s+", '', value, flags=re.I)
        return 'tu as ' + value

    def _friendly_day(self, value, today):
        day = date.fromisoformat(value)
        if day == today:
            return "aujourd'hui"
        if day == today - timedelta(days=1):
            return "hier"
        return day.strftime('le %d/%m/%Y')

    def rollover(self):
        today = self.agenda._now().date().isoformat()
        with self.agenda._connect() as db:
            rows = db.execute("SELECT * FROM agenda_items WHERE kind='todo' AND status='pending' AND due_date<?", (today,)).fetchall()
            for row in rows:
                meta = json.loads(row['metadata_json'])
                if meta.get('backlog_undated'): continue
                meta.setdefault('first_due_date', row['due_date'])
                meta['previous_due_date'] = row['due_date']
                meta['reschedule_count'] = int(meta.get('reschedule_count',0)) + 1
                db.execute('UPDATE agenda_items SET due_date=?,metadata_json=?,updated_at=? WHERE id=?',
                    (today,json.dumps(meta),self.agenda._now().isoformat(),row['id']))

    def rows(self, start, end, query=''):
        with self.agenda._connect() as db:
            rows = [dict(r) for r in db.execute('SELECT id,day,title,kind,source FROM life_events WHERE day BETWEEN ? AND ? ORDER BY day,id',(start,end))]
            # Read completed tasks from their authoritative table, without copying them.
            for r in db.execute("SELECT * FROM agenda_items WHERE kind='todo' AND status='done' AND substr(completed_at,1,10) BETWEEN ? AND ?",(start,end)):
                if not any(x['day']==r['completed_at'][:10] and norm(x['title'])==norm(r['title']) for x in rows):
                    rows.append(dict(id='T-'+str(r['id']),day=r['completed_at'][:10],title=r['title'],kind='action',source=r['source_text']))
        words=[w for w in re.findall(r'\w+',norm(query)) if len(w)>2 and w not in {'les','des','une','que','fait','fois','dans','pour','mon','mes','sur','trois','derniers','mois','depuis','est','quand','combien','jai'}]
        return [r for r in rows if not words or all(w in norm(r['title']) for w in words)]

    def handle(self, text):
        self.rollover()
        n=norm(text).replace('’',"'")
        today=self.agenda._now().date()
        m=re.fullmatch(r'journal supprimer (\d+)',n)
        if m:
            with self.agenda._connect() as db:
                c=db.execute('DELETE FROM life_events WHERE id=?',(int(m[1]),))
            return 'Entrée supprimée.' if c.rowcount else 'Entrée introuvable.'
        # Explicit journal entry or a completed first-person statement, never a question/negation.
        capture=n.startswith('journal :') or n.startswith('journal:') or bool(re.match(r"(?:(?:aujourd'hui|hier)[, ]+)?j'ai (?:fait|nettoye|change|termine|achete|repare|arrose|range|lave|tondu)\b",n))
        if capture and '?' not in text and not re.search(r"\b(?:pas|jamais|peut-etre|si)\b",n):
            resolved=self.agenda.resolve_date(text,reference=self.agenda._now())
            day=resolved.value if resolved else today
            if day>today: return 'Cette date est future : ajoute plutôt une tâche à faire.'
            payload=re.sub(r'^journal\s*:\s*','',text,flags=re.I)
            payload=re.sub(r"^(?:aujourd'hui|hier)[, ]+",'',payload,flags=re.I)
            parts=[p.strip() for p in re.split(r';|\n|,\s+|\s+et\s+(?=j[’\']ai)',payload) if p.strip()]
            recorded=[]
            duplicates=[]
            completed_now=[]
            for part in parts:
                # Complete a confidently matched task, preserving its single authoritative record.
                completion_payload = re.sub(r"^j[’']ai\s+(?:fait\s+)?", '', part, flags=re.I)
                completion = self.agenda.complete_todo("c'est fait pour " + completion_payload) if day == today else None
                if completion and "est fait" in completion:
                    completed_now.append(completion_payload)
                    continue
                with self.agenda._connect() as db:
                    completed = [dict(r) for r in db.execute("SELECT * FROM agenda_items WHERE kind='todo' AND status='done' AND substr(completed_at,1,10)=?", (day.isoformat(),))]
                if any(self.agenda._todo_match_score(completion_payload, item) >= 0.9 for item in completed):
                    duplicates.append(completion_payload)
                    continue
                ident,new=self.add(part,day.isoformat(),source=text)
                if new:
                    recorded.append(part)
                else:
                    duplicates.append(part)

            all_new = recorded + completed_now
            answers=[]
            if all_new:
                actions=self._natural_list([self._as_user_action(item) for item in all_new])
                answers.append(f"C'est noté pour {self._friendly_day(day.isoformat(), today)} : {actions}.")
            if completed_now:
                answers.append("J'ai aussi retiré " + self._natural_list(completed_now) + " de ce qu'il te restait à faire.")
            if duplicates:
                already=self._natural_list(duplicates)
                answers.append(f"J'avais déjà noté {already}, donc je ne l'ai pas compté deux fois.")
            return ' '.join(answers)
        if n.startswith('humeur:') or n.startswith('humeur :'):
            payload=text.split(':',1)[1].strip()
            _, created = self.add(payload,today.isoformat(),'humeur',text)
            if not created:
                return "Oui, je l'avais déjà noté pour aujourd'hui."
            return f"Je vois : {payload}. Je garde ça comme ton ressenti d'aujourd'hui."
        if n.startswith('journal') or 'combien de fois' in n or 'quand est-ce que j' in n:
            start=date(1970,1,1); end=today
            m=re.search(r'(\d+|trois|six|deux)\s+(?:derniers\s+)?mois',n)
            if m:
                count={'trois':3,'six':6,'deux':2}.get(m[1],int(m[1]) if m[1].isdigit() else 3)
                if count>1200: return 'Choisis une période de 1 à 1200 mois.'
                idx=today.year*12+today.month-1-count
                y,mo=divmod(idx,12); start=date(y,mo+1,min(today.day,calendar.monthrange(y,mo+1)[1]))
            else:
                resolved=self.agenda.resolve_date(text,reference=self.agenda._now())
                if resolved: start=end=resolved.value
            q=''
            if ':' in text: q=text.split(':',1)[1]
            elif 'combien de fois' in n or 'quand est-ce' in n:
                q=re.sub(r'^.*?j[’\']ai\s*','',text,flags=re.I)
                q=re.split(r'\s+(?:sur|dans|depuis|ces)\s+',q,flags=re.I)[0].strip(' ?')
            q=re.sub(r'\b(?:le|la|les|un|une|du|des)\b',' ',q,flags=re.I)
            rows=self.rows(start.isoformat(),end.isoformat(),q)
            period = (
                f"sur les {m.group(1)} derniers mois"
                if m
                else f"entre le {start:%d/%m/%Y} et le {end:%d/%m/%Y}"
            )
            if not rows:
                subject = f" pour « {q.strip()} »" if q.strip() else ''
                return f"Je n'ai rien retrouvé{subject} {period}."

            if q.strip():
                count = len(rows)
                answer = (
                    f"Je l'ai retrouvé une fois {period}"
                    if count == 1
                    else f"Je l'ai retrouvé {count} fois {period}"
                )
                details = self._natural_list([
                    f"{self._friendly_day(row['day'], today)}, {self._as_user_action(row['title'])}"
                    for row in rows[-10:]
                ])
                suffix = " Je te montre seulement les 10 plus récentes." if count > 10 else ''
                return answer + ' : ' + details + '.' + suffix

            heading = (
                "J'ai retrouvé une chose"
                if len(rows) == 1
                else f"J'ai retrouvé {len(rows)} choses"
            )
            details='\n'.join(
                f"- {self._friendly_day(row['day'], today)} : {self._as_user_action(row['title'])}"
                for row in rows[-100:]
            )
            suffix = '\nJe te montre les 100 plus récentes.' if len(rows)>100 else ''
            return f"{heading} {period} :\n{details}{suffix}"
        return None

    def notifications(self):
        self.rollover()
        now=self.agenda._now(); today=now.date()
        notices=[]
        candidates=[]
        if now.hour>=8:
            candidates.append((f'daily:{today}',self.agenda.program_for_date(today)))
        for item in self.agenda.items_for_date(today,kind='appointment'):
            if item.get('status')!='pending' or not item.get('start_time'): continue
            try:
                h,m=map(int,item['start_time'].split(':')[:2]); at=now.replace(hour=h,minute=m,second=0,microsecond=0)
            except ValueError: continue
            if timedelta(0)<=at-now<=timedelta(minutes=30):
                candidates.append((f"rdv:{item['id']}:{today}:{item['start_time']}",f"Rappel : {item['title']} à {item['start_time']}."))
        with self.agenda._connect() as db:
            for key,message in candidates:
                if db.execute('INSERT OR IGNORE INTO life_notices VALUES(?)',(key,)).rowcount: notices.append(message)
        return notices
