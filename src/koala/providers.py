"""Small HTTP client: credentials stay in environment variables, never artifacts."""
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, payload=None, key=None, timeout=180):
    headers = {'Accept': 'application/json', 'User-Agent': 'KOALA/0.1 (scholarly drafting)'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode()
    for attempt in range(3):
        try:
            with build_opener(NoRedirect).open(Request(url, data=data, headers=headers), timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {exc.code} from {urlparse(url).netloc}. Check credentials, endpoint, model access, and rate limits.") from None
        except (URLError, TimeoutError):
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Cannot reach {urlparse(url).netloc}; check network/VPN and retry.") from None
    raise RuntimeError('Request failed.')


class Provider:
    def __init__(self, name='openai', model=None, base_url=None):
        self.name = name
        self.key = os.environ.get('OPENAI_API_KEY' if name == 'openai' else 'ARC_API_KEY')
        if not self.key:
            raise ValueError(f"Set {'OPENAI_API_KEY' if name == 'openai' else 'ARC_API_KEY'} in your environment.")
        self.base = (base_url or os.environ.get(f'{name.upper()}_BASE_URL') or
                     ('https://api.openai.com/v1' if name == 'openai' else 'https://llm-api.arc.vt.edu/api/v1')).rstrip('/')
        if urlparse(self.base).scheme != 'https':
            raise ValueError('Provider base URL must use HTTPS.')
        self.model = model or ('gpt-6-luna' if name == 'openai' else 'gpt-oss-120b')

    def models(self):
        data = request_json(self.base + '/models', key=self.key)
        return sorted(m['id'] for m in data.get('data', []) if isinstance(m, dict) and 'id' in m)

    def check_model(self):
        if self.model not in self.models():
            raise ValueError(f"Model {self.model!r} is not available to this account. Run koala models --provider {self.name} and choose --model. No model was substituted.")

    def generate(self, instructions, prompt):
        if self.name == 'openai':
            result = request_json(self.base + '/responses', {
                'model': self.model, 'instructions': instructions, 'input': prompt,
                'max_output_tokens': 8000, 'store': False}, self.key)
            if result.get('status') != 'completed':
                raise RuntimeError('OpenAI response was incomplete. Reduce section size or choose another model.')
            text = '\n'.join(c.get('text', '') for o in result.get('output', [])
                             for c in o.get('content', []) if c.get('type') == 'output_text')
        else:
            result = request_json(self.base + '/chat/completions', {
                'model': self.model, 'messages': [{'role': 'system', 'content': instructions},
                                                {'role': 'user', 'content': prompt}],
                'max_tokens': 8000}, self.key)
            choice = result.get('choices', [{}])[0]
            if choice.get('finish_reason') not in ('stop',):
                raise RuntimeError('ARC response was incomplete or refused. Reduce section size or choose another model.')
            text = choice.get('message', {}).get('content') or ''
        if not text.strip():
            raise RuntimeError('Provider returned no usable text.')
        return text.strip()

    def json(self, instructions, prompt):
        raw = self.generate(instructions + '\nReturn only one valid JSON object, without code fences.', prompt)
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError:
            raise RuntimeError('Model returned invalid JSON; checkpoint retained. Retry or select another model.') from None
