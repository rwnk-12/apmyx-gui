from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from core.hints import certificate_hint, explain

MAC_ERROR = ("Failed to fetch song details: Cannot connect to host aod.itunes.apple.com:443 ssl:True "
             "[SSLCertVerificationError: (1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
             "self-signed certificate in certificate chain (ssl.c:1081)')]")
ORDER_CHECK = (
    "import ssl, truststore, aiohttp.connector as c; "
    "ctx = getattr(c, '_SSL_CONTEXT_VERIFIED', None); "
    "print(ssl.SSLContext is truststore.SSLContext and (ctx is None or type(ctx).__module__.startswith('truststore')), flush=True)"
)


class CertificateHintTests(unittest.TestCase):
    def test_intercepted_connection_is_explained(self):
        hint = certificate_hint(MAC_ERROR)
        self.assertIn("antivirus", hint)
        self.assertNotIn(";", hint)
        self.assertTrue(explain(MAC_ERROR).startswith(MAC_ERROR))
        self.assertTrue(explain(MAC_ERROR).endswith(hint))

    def test_other_verification_failures_and_unrelated_errors(self):
        missing = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"
        self.assertIn("date and time", certificate_hint(missing))
        self.assertEqual(certificate_hint("Wrapper Lite downloaded 0 of 1 tracks. Timed out"), "")
        self.assertEqual(explain("Network unreachable"), "Network unreachable")


class ImportPathTests(unittest.TestCase):
    def test_core_modules_import_from_src_without_the_repo_root_on_the_path(self):
        import os
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        code = (f"import sys; sys.path[0] = {str(ROOT / 'src')!r}; "
                f"assert {str(ROOT)!r} not in sys.path; import core.hints, core.config; print('ok')")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT / "src", env=env, timeout=60)
        self.assertEqual(result.stdout.strip(), "ok", result.stderr[-1500:])


class TrustStoreOrderTests(unittest.TestCase):
    def setUp(self):
        try:
            import truststore
        except ImportError:
            self.skipTest("truststore is not installed")

    def run_check(self, setup, env=None):
        result = subprocess.run([sys.executable, "-c", setup + "; " + ORDER_CHECK + "; import os; os._exit(0)"],
                                capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)
        self.assertEqual(result.stdout.strip().splitlines()[-1:], ["True"], result.stderr[-2000:])

    def test_bridge_trusts_the_system_store_before_aiohttp_loads(self):
        import os
        env = {**os.environ, "PYTHONPATH": str(ROOT / "backend" / "runtime")}
        self.run_check(f"import sys; sys.path.insert(0, {str(ROOT / 'backend')!r}); import bridge", env)

    def test_app_trusts_the_system_store_before_aiohttp_loads(self):
        self.run_check(f"import sys; sys.path[:0] = [{str(ROOT / 'src')!r}, {str(ROOT)!r}]; import main")


if __name__ == "__main__":
    unittest.main()
