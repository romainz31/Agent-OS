"""Exercise the production entry point with an isolated runtime."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

def main():
    with tempfile.TemporaryDirectory() as t:
        os.environ['AGENTOS_DATA_DIR']=t+'/data'
        os.environ['AGENTOS_WORKSPACE_DIR']=t+'/workspace'
        from fastapi.testclient import TestClient
        import api_server
        with TestClient(api_server.api_module.app) as client:
            for url in ['/api/health','/api/life','/api/documents/exports','/']:
                assert client.get(url).status_code==200, url
            r=client.post('/api/documents/upload',files={'file':('../../invoice.txt',b'Invoice total 120 EUR')},data={'objective':'recapitulatif Excel'})
            assert r.status_code==200 and 'M-' in r.json()['response']
            assert len(list(Path(t+'/workspace/inbox').glob('*/document.txt')))==1
            assert client.post('/api/documents/upload',files={'file':('run.exe',b'x')}).status_code==400
            assert client.post('/api/documents/upload',files={'file':('empty.txt',b'')}).status_code==413
            r=client.post('/api/chat',json={'message':'Journal : arrosé les plantes; nettoyé la cuisine'})
            assert r.status_code==200 and "C'est noté pour aujourd'hui" in r.json()['response']
            assert len(client.get('/api/life').json()['events'])==2
            assert client.get('/api/life?start=incorrect').status_code==400

            headers={'X-AgentOS-Client':'test-photo-client'}
            r=client.post(
                '/api/documents/upload',
                files={'file':('aquarium.jpg',b'fake-image-for-routing-test')},
                data={'objective':''},
                headers=headers,
            )
            assert r.status_code==200
            assert r.json()['awaiting_instruction'] is True
            assert "Qu'est-ce que tu veux" in r.json()['response']
            assert 'M-' not in r.json()['response']

            r=client.post(
                '/api/chat',
                json={'message':'Décris-moi ce que tu vois sur cette image'},
                headers=headers,
            )
            assert r.status_code==200 and 'M-' in r.json()['response']

            cancel_headers={'X-AgentOS-Client':'test-cancel-client'}
            client.post(
                '/api/documents/upload',
                files={'file':('autre.jpg',b'fake-image')},
                data={'objective':''},
                headers=cancel_headers,
            )
            r=client.post('/api/chat',json={'message':'Laisse tomber'},headers=cancel_headers)
            assert r.status_code==200 and 'laisse cette image de côté' in r.json()['response']
        print('API V10 : routes, upload isolé, formats, autorisation M-xxx, journal et dates OK')

if __name__=='__main__':main()
