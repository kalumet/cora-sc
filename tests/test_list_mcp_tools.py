import asyncio
from io import StringIO
from types import SimpleNamespace
import unittest

import yaml

from scripts.list_mcp_tools import configured_servers, list_server_tools, run


class ListMcpToolsTests(unittest.TestCase):
    def setUp(self):
        self.connections = []
        owner = self
        class FakeClient:
            def __init__(self, url, **kwargs):
                owner.connections.append(url)
                if url.endswith('/offline'):
                    raise ConnectionError('must not reveal credentials')
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def list_tools(self, cursor=None):
                tool = SimpleNamespace(name='sc_mining' if cursor else 'sc_search',
                                       title=None, description='Mining\nSecond line',
                                       input_schema={'type': 'object'})
                return SimpleNamespace(tools=[tool], next_cursor=None if cursor else 'next')
            async def call_tool(self, *args):
                raise AssertionError('Discovery must never execute a tool')
        self.factory = FakeClient
        self.config = {'mcp': {'servers': {'shared': {'url': 'https://example.com/global'}}},
                       'wingmen': {'cora': {'mcp': {'servers': {
                           'starhead': {'enabled': True, 'url': 'https://example.com/mining'},
                           'disabled': {'enabled': False, 'url': 'https://example.com/disabled'},
                       }}}, 'other': {'mcp': {'servers': {'another': {
                           'enabled': True, 'url': 'https://example.com/other'}}}}}}

    def execute(self, **kwargs):
        stdout, stderr = StringIO(), StringIO()
        status = asyncio.run(run(self.config, stdout=stdout, stderr=stderr,
                                 client_factory=self.factory, **kwargs))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_all_scopes_including_disabled_servers_and_all_pages(self):
        status, output, errors = self.execute()
        self.assertEqual(0, status)
        self.assertEqual('', errors)
        self.assertEqual(4, len(self.connections))
        documents = list(yaml.safe_load_all(output))
        self.assertEqual(4, len(documents))
        self.assertEqual(['sc_mining', 'sc_search'], documents[1]['starhead'])
        self.assertIn('deaktiviert', output)

    def test_wingman_and_enabled_filters(self):
        status, output, _ = self.execute(wingman='cora', enabled_only=True)
        self.assertEqual(0, status)
        self.assertEqual(['https://example.com/mining'], self.connections)
        self.assertEqual([{'starhead': ['sc_mining', 'sc_search']}], list(yaml.safe_load_all(output)))

    def test_one_failure_does_not_hide_other_servers(self):
        self.config['mcp']['servers']['shared']['url'] = 'https://example.com/offline'
        status, output, errors = self.execute()
        self.assertEqual(1, status)
        self.assertIn('global/shared', errors)
        self.assertNotIn('credentials', errors)
        self.assertEqual(3, len(list(yaml.safe_load_all(output))))

    def test_details_remain_valid_yaml(self):
        _, output, _ = self.execute(wingman='cora', enabled_only=True, details=True)
        self.assertIn('# Second line', output)
        self.assertIn('#   "type": "object"', output)
        self.assertEqual([{'starhead': ['sc_mining', 'sc_search']}], list(yaml.safe_load_all(output)))

    def test_unknown_wingman_and_invalid_url(self):
        with self.assertRaises(ValueError):
            list(configured_servers(self.config, 'missing'))
        for options in ({'url': 'file:///secret'}, {'url': 'https://example.com', 'timeout_seconds': -1}):
            with self.assertRaises(ValueError):
                asyncio.run(list_server_tools(options, self.factory))
        self.assertEqual([], self.connections)


if __name__ == '__main__':
    unittest.main()
