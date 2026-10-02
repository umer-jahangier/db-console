import http.client
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

import app


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.creds = os.path.join(self.tmp.name, "credentials")
        self.backups = os.path.join(self.tmp.name, "backups")
        os.makedirs(self.creds)
        os.makedirs(self.backups)
        for name, value in (("root_password", "rootpw"), ("app_password", "app/pw?"), ("api_key", "key123")):
            with open(os.path.join(self.creds, name), "w") as handle:
                handle.write(value + "\n")
        with open(os.path.join(self.backups, "shopdb-20261002-020000.archive.gz"), "wb") as handle:
            handle.write(b"dump")
        with open(os.path.join(self.tmp.name, "outside.txt"), "w") as handle:
            handle.write("secret outside")
        os.environ.update({
            "ENGINE": "mongodb", "WORKLOAD": "shopdb", "HOST": "shopdb.juno.svc.cluster.local", "PORT": "27017",
            "DATABASE": "app", "APP_USER": "app", "ADMIN_USER": "root", "CREDENTIALS_DIR": self.creds,
            "BACKUPS_DIR": self.backups, "BASE_PATH": "/juno/mongodb/shopdb/",
        })
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        conn.request(method, path)
        res = conn.getresponse()
        return res.status, res.read(), dict(res.getheaders())

    def test_page_under_base_path(self):
        status, body, headers = self.get("/juno/mongodb/shopdb/")
        self.assertEqual(status, 200)
        self.assertIn(b"shopdb.juno.svc.cluster.local", body)
        self.assertIn(b"mongodb://app:app%2Fpw%3F@shopdb.juno.svc.cluster.local:27017/app", body)
        self.assertIn(b"mongodb://root:rootpw@shopdb.juno.svc.cluster.local:27017/?authSource=admin", body)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_base_without_slash_redirects(self):
        status, _, headers = self.get("/juno/mongodb/shopdb")
        self.assertEqual(status, 308)
        self.assertEqual(headers["Location"], "/juno/mongodb/shopdb/")

    def test_backup_download(self):
        status, body, headers = self.get("/juno/mongodb/shopdb/backups/shopdb-20261002-020000.archive.gz")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"dump")
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_path_traversal_refused(self):
        for path in ("/juno/mongodb/shopdb/backups/../outside.txt", "/juno/mongodb/shopdb/backups/%2e%2e%2foutside.txt",
                     "/juno/mongodb/shopdb/backups/..%2Foutside.txt", "/juno/mongodb/shopdb/backups/../credentials/root_password"):
            status, body, _ = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"secret", body)
            self.assertNotIn(b"rootpw", body)

    def test_only_get_and_head(self):
        status, _, headers = self.get("/juno/mongodb/shopdb/", "POST")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET, HEAD")

    def test_values_are_escaped(self):
        os.environ["WORKLOAD"] = "<script>x</script>"
        status, body, _ = self.get("/juno/mongodb/shopdb/")
        self.assertEqual(status, 200)
        self.assertNotIn(b"<script>x</script>", body)

    def test_engines_build_their_own_strings(self):
        cases = {
            "postgres": "postgresql://app:app%2Fpw%3F@h:5432/app",
            "mysql": "mysql://app:app%2Fpw%3F@h:5432/app",
            "redis": "redis://default:rootpw@h:5432/0",
            "qdrant": "http://h:5432",
        }
        for engine, expected in cases.items():
            cfg = dict(app.config(), engine=engine, host="h", port="5432")
            uris = [row[3] for row in app.connection_strings(cfg)]
            self.assertIn(expected, uris, engine)

    def test_missing_credentials_do_not_crash(self):
        os.environ["CREDENTIALS_DIR"] = os.path.join(self.tmp.name, "missing")
        status, body, _ = self.get("/juno/mongodb/shopdb/")
        self.assertEqual(status, 200)
        self.assertIn(b"Not generated yet", body)

    def test_health(self):
        self.assertEqual(self.get("/juno/mongodb/shopdb/healthz")[0], 200)


if __name__ == "__main__":
    unittest.main()
