import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_node(script):
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"node script failed with exit {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


class PackagedRuntimeProvenanceTests(unittest.TestCase):
    def test_packaged_production_rejects_arbitrary_eii_python(self):
        script = r"""
            const runtime = require('./ui/backend-runtime');
            const command = 'C:\\Users\\attacker\\python.exe';
            const result = { rejected: false, message: '' };
            try {
              runtime.validatePythonProvenance({
                command,
                app: { isPackaged: true },
                env: { EII_PYTHON: command },
                trustedRoots: ['C:\\Program Files\\Esports Isolator PRO\\python'],
                isPathWritableByStandardUsers: () => false
              });
            } catch (error) {
              result.rejected = true;
              result.message = error.message;
            }
            console.log(JSON.stringify(result));
        """
        result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("trusted", result["message"].lower())

    def test_packaged_production_rejects_relative_eii_python(self):
        script = r"""
            const runtime = require('./ui/backend-runtime');
            const result = { rejected: false, message: '' };
            try {
              runtime.validatePythonProvenance({
                command: '.\\python.exe',
                trustedRoots: ['C:\\Program Files\\Esports Isolator PRO\\python'],
                isPathWritableByStandardUsers: () => false
              });
            } catch (error) {
              result.rejected = true;
              result.message = error.message;
            }
            console.log(JSON.stringify(result));
        """
        result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("absolute", result["message"].lower())

    def test_packaged_production_requires_explicit_dev_override_for_eii_python(self):
        script = r"""
            const runtime = require('./ui/backend-runtime');
            const command = 'C:\\Tools\\Python312\\python.exe';
            const denied = { rejected: false, message: '' };
            try {
              runtime.resolvePackagedPythonCommand({
                env: { EII_PYTHON: command },
                app: { isPackaged: true },
                trustedRoots: ['C:\\Program Files\\Esports Isolator PRO\\python'],
                isPathWritableByStandardUsers: () => false
              });
            } catch (error) {
              denied.rejected = true;
              denied.message = error.message;
            }
            const allowed = runtime.resolvePackagedPythonCommand({
              env: {
                EII_PYTHON: command,
                EII_ALLOW_UNTRUSTED_PACKAGED_PYTHON: '1'
              },
              app: { isPackaged: true },
              isProduction: false,
              trustedRoots: ['C:\\Program Files\\Esports Isolator PRO\\python'],
              isPathWritableByStandardUsers: () => false
            });
            console.log(JSON.stringify({ denied, allowed }));
        """
        result = run_node(script)

        self.assertTrue(result["denied"]["rejected"])
        self.assertIn("developer override", result["denied"]["message"].lower())
        self.assertEqual("C:\\Tools\\Python312\\python.exe", result["allowed"])

    def test_packaged_runtime_dev_override_cannot_be_enabled_by_inherited_env(self):
        script = r"""
            const runtime = require('./ui/backend-runtime');
            const command = 'C:\\Tools\\Python312\\python.exe';
            const cases = [
              { NODE_ENV: 'development' },
              { EII_PACKAGED_RUNTIME_DEV: '1' }
            ];
            const results = cases.map((extraEnv) => {
              const result = { rejected: false, message: '' };
              try {
                runtime.resolvePackagedPythonCommand({
                  env: {
                    EII_PYTHON: command,
                    EII_ALLOW_UNTRUSTED_PACKAGED_PYTHON: '1',
                    ...extraEnv
                  },
                  app: { isPackaged: true },
                  trustedRoots: ['C:\\Program Files\\Esports Isolator PRO\\python'],
                  isPathWritableByStandardUsers: () => false
                });
              } catch (error) {
                result.rejected = true;
                result.message = error.message;
              }
              return result;
            });
            console.log(JSON.stringify(results));
        """
        results = run_node(script)

        self.assertTrue(all(result["rejected"] for result in results))
        self.assertTrue(all("production" in result["message"].lower() for result in results))

    def test_packaged_python_dev_override_rejects_relative_path(self):
        script = r"""
            const runtime = require('./ui/backend-runtime');
            const result = { rejected: false, message: '' };
            try {
              runtime.resolvePackagedPythonCommand({
                env: {
                  EII_PYTHON: '.\\python.exe',
                  EII_ALLOW_UNTRUSTED_PACKAGED_PYTHON: '1'
                },
                app: { isPackaged: true },
                isProduction: false,
                trustedRoots: ['C:\\Program Files\\Esports Isolator PRO\\python'],
                isPathWritableByStandardUsers: () => false
              });
            } catch (error) {
              result.rejected = true;
              result.message = error.message;
            }
            console.log(JSON.stringify(result));
        """
        result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("absolute", result["message"].lower())

    def test_packaged_production_accepts_trusted_python_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            trusted_root = (Path(tmp) / "python").resolve()
            trusted_root.mkdir()
            command = trusted_root / "python.exe"
            command.write_text("trusted runtime placeholder\n", encoding="utf-8")
            script = rf"""
                const runtime = require('./ui/backend-runtime');
                const command = {json.dumps(str(command))};
                const resolved = runtime.validatePythonProvenance({{
                  command,
                  app: {{ isPackaged: true }},
                  env: {{ EII_PYTHON: command }},
                  trustedRoots: [{json.dumps(str(trusted_root))}],
                  isPathWritableByStandardUsers: () => false
                }});
                console.log(JSON.stringify({{ resolved }}));
            """
            result = run_node(script)

        self.assertEqual(str(command), result["resolved"])

    def test_packaged_production_rejects_missing_trusted_python_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            trusted_root = Path(tmp) / "python"
            command = trusted_root / "python.exe"
            script = rf"""
                const runtime = require('./ui/backend-runtime');
                const command = {json.dumps(str(command))};
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.resolvePackagedPythonCommand({{
                    env: {{}},
                    app: {{ isPackaged: true }},
                    bundledPythonPath: command,
                    trustedRoots: [{json.dumps(str(trusted_root))}],
                    isPathWritableByStandardUsers: () => false
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("missing", result["message"].lower())

    def test_packaged_production_rejects_standard_user_writable_python_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            trusted_root = (Path(tmp) / "python").resolve()
            trusted_root.mkdir()
            command = trusted_root / "python.exe"
            command.write_text("trusted runtime placeholder\n", encoding="utf-8")
            script = rf"""
                const runtime = require('./ui/backend-runtime');
                const command = {json.dumps(str(command))};
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.validatePythonProvenance({{
                    command,
                    app: {{ isPackaged: true }},
                    env: {{ EII_PYTHON: command }},
                    trustedRoots: [{json.dumps(str(trusted_root))}],
                    isPathWritableByStandardUsers: () => true
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("writable", result["message"].lower())

    def test_main_runs_provenance_before_python_preflight_and_spawn(self):
        main = (ROOT / "ui" / "electron-main.js").read_text(encoding="utf-8")

        self.assertIn("resolvePackagedPythonCommand", main)
        self.assertIn("verifyBackendResourceIntegrity", main)
        launch_body = main[main.index("async function launchBackendProcess"):]
        launch_body = launch_body[: launch_body.index("function attachBackendHandlers")]
        resolve_index = launch_body.index("resolvePackagedPythonCommand")
        integrity_index = launch_body.index("verifyBackendResourceIntegrity")
        preflight_index = launch_body.index("preflightPythonRuntime")
        spawn_index = launch_body.index("spawnBackendOnce")
        self.assertLess(integrity_index, preflight_index)
        self.assertLess(resolve_index, preflight_index)
        self.assertLess(preflight_index, spawn_index)


class BackendResourceIntegrityTests(unittest.TestCase):
    def test_backend_manifest_verification_rejects_tampered_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            backend.mkdir()
            target = backend / "server.py"
            target.write_text("safe\n", encoding="utf-8")
            manifest = root / "backend-manifest.json"
            script = rf"""
                const fs = require('fs');
                const crypto = require('crypto');
                const runtime = require('./ui/backend-runtime');
                const backendRoot = {json.dumps(str(backend))};
                const target = {json.dumps(str(target))};
                const manifestPath = {json.dumps(str(manifest))};
                const original = fs.readFileSync(target);
                const digest = crypto.createHash('sha256').update(original).digest('hex');
                fs.writeFileSync(manifestPath, JSON.stringify({{
                  version: 1,
                  algorithm: 'sha256',
                  files: {{ 'server.py': `sha256-${{digest}}` }}
                }}));
                fs.writeFileSync(target, 'tampered\n');
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.verifyBackendResourceIntegrity({{
                    backendRoot,
                    manifestPath,
                    isPathWritableByStandardUsers: () => false
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("hash", result["message"].lower())

    def test_backend_manifest_verification_rejects_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = Path(tmp) / "backend"
            backend.mkdir()
            script = rf"""
                const runtime = require('./ui/backend-runtime');
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.verifyBackendResourceIntegrity({{
                    backendRoot: {json.dumps(str(backend))},
                    manifestPath: {json.dumps(str(Path(tmp) / "missing.json"))},
                    isPathWritableByStandardUsers: () => false
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("manifest", result["message"].lower())

    def test_backend_manifest_verification_rejects_manifest_under_backend_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            backend.mkdir()
            manifest = backend / "backend-manifest.json"
            manifest.write_text(
                json.dumps({"version": 1, "algorithm": "sha256", "files": {}}),
                encoding="utf-8",
            )
            script = rf"""
                const runtime = require('./ui/backend-runtime');
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.verifyBackendResourceIntegrity({{
                    backendRoot: {json.dumps(str(backend))},
                    manifestPath: {json.dumps(str(manifest))},
                    isPathWritableByStandardUsers: () => false
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("trusted app bundle", result["message"].lower())

    def test_backend_manifest_verification_rejects_writable_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            backend.mkdir()
            (backend / "server.py").write_text("safe\n", encoding="utf-8")
            manifest = root / "backend-manifest.json"
            script = rf"""
                const fs = require('fs');
                const crypto = require('crypto');
                const runtime = require('./ui/backend-runtime');
                const backendRoot = {json.dumps(str(backend))};
                const manifestPath = {json.dumps(str(manifest))};
                const server = fs.readFileSync(require('path').join(backendRoot, 'server.py'));
                const digest = crypto.createHash('sha256').update(server).digest('hex');
                fs.writeFileSync(manifestPath, JSON.stringify({{
                  version: 1,
                  algorithm: 'sha256',
                  files: {{ 'server.py': `sha256-${{digest}}` }}
                }}));
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.verifyBackendResourceIntegrity({{
                    backendRoot,
                    manifestPath,
                    isPathWritableByStandardUsers: (target) => target === manifestPath
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("manifest", result["message"].lower())
        self.assertIn("writable", result["message"].lower())

    def test_backend_manifest_verification_rejects_unlisted_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            backend.mkdir()
            (backend / "server.py").write_text("safe\n", encoding="utf-8")
            (backend / "extra.py").write_text("unlisted\n", encoding="utf-8")
            manifest = root / "backend-manifest.json"
            script = rf"""
                const fs = require('fs');
                const crypto = require('crypto');
                const runtime = require('./ui/backend-runtime');
                const backendRoot = {json.dumps(str(backend))};
                const manifestPath = {json.dumps(str(manifest))};
                const server = fs.readFileSync(require('path').join(backendRoot, 'server.py'));
                const digest = crypto.createHash('sha256').update(server).digest('hex');
                fs.writeFileSync(manifestPath, JSON.stringify({{
                  version: 1,
                  algorithm: 'sha256',
                  files: {{ 'server.py': `sha256-${{digest}}` }}
                }}));
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.verifyBackendResourceIntegrity({{
                    backendRoot,
                    manifestPath,
                    isPathWritableByStandardUsers: () => false
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("not listed", result["message"].lower())

    def test_backend_manifest_verification_rejects_unlisted_backend_junction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            backend.mkdir()
            (backend / "server.py").write_text("safe\n", encoding="utf-8")
            manifest = root / "backend-manifest.json"
            linked_source = root / "linked-source"
            linked_source.mkdir()
            (linked_source / "extra.py").write_text("unlisted\n", encoding="utf-8")
            script = rf"""
                const fs = require('fs');
                const crypto = require('crypto');
                const path = require('path');
                const runtime = require('./ui/backend-runtime');
                const backendRoot = {json.dumps(str(backend))};
                const manifestPath = {json.dumps(str(manifest))};
                const linkedSource = {json.dumps(str(linked_source))};
                const linkPath = path.join(backendRoot, 'linked');
                fs.symlinkSync(linkedSource, linkPath, 'junction');
                const server = fs.readFileSync(path.join(backendRoot, 'server.py'));
                const digest = crypto.createHash('sha256').update(server).digest('hex');
                fs.writeFileSync(manifestPath, JSON.stringify({{
                  version: 1,
                  algorithm: 'sha256',
                  files: {{ 'server.py': `sha256-${{digest}}` }}
                }}));
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.verifyBackendResourceIntegrity({{
                    backendRoot,
                    manifestPath,
                    isPathWritableByStandardUsers: () => false
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("not listed", result["message"].lower())

    def test_backend_manifest_verification_rejects_unsafe_acl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            backend.mkdir()
            (backend / "server.py").write_text("safe\n", encoding="utf-8")
            manifest = root / "backend-manifest.json"
            script = rf"""
                const fs = require('fs');
                const crypto = require('crypto');
                const runtime = require('./ui/backend-runtime');
                const backendRoot = {json.dumps(str(backend))};
                const manifestPath = {json.dumps(str(manifest))};
                const server = fs.readFileSync(require('path').join(backendRoot, 'server.py'));
                const digest = crypto.createHash('sha256').update(server).digest('hex');
                fs.writeFileSync(manifestPath, JSON.stringify({{
                  version: 1,
                  algorithm: 'sha256',
                  files: {{ 'server.py': `sha256-${{digest}}` }}
                }}));
                const result = {{ rejected: false, message: '' }};
                try {{
                  runtime.verifyBackendResourceIntegrity({{
                    backendRoot,
                    manifestPath,
                    isPathWritableByStandardUsers: () => true
                  }});
                }} catch (error) {{
                  result.rejected = true;
                  result.message = error.message;
                }}
                console.log(JSON.stringify(result));
            """
            result = run_node(script)

        self.assertTrue(result["rejected"])
        self.assertIn("writable", result["message"].lower())

    def test_acl_parser_rejects_well_known_standard_user_sids(self):
        script = r"""
            const runtime = require('./ui/backend-runtime');
            const samples = {
              everyone: 'C:\\app S-1-1-0:(I)(W)',
              authenticatedUsers: 'C:\\app S-1-5-11:(I)(M)',
              users: 'C:\\app S-1-5-32-545:(I)(F)',
              usersWordRights: 'S-1-5-32-545 Allow Modify, Synchronize',
              denyOnly: 'C:\\app S-1-5-32-545:(DENY)(W)'
            };
            const result = Object.fromEntries(
              Object.entries(samples).map(([name, acl]) => [name, runtime.aclGrantsStandardUserWrite(acl)])
            );
            console.log(JSON.stringify(result));
        """
        result = run_node(script)

        self.assertTrue(result["everyone"])
        self.assertTrue(result["authenticatedUsers"])
        self.assertTrue(result["users"])
        self.assertTrue(result["usersWordRights"])
        self.assertFalse(result["denyOnly"])

    def test_package_declares_manifest_generation_and_packaged_runtime_verification(self):
        package = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))

        self.assertEqual(
            "node scripts/generate-backend-manifest.js",
            package["scripts"]["build:backend-manifest"],
        )
        self.assertEqual(
            "node scripts/verify-packaged-runtime.js",
            package["scripts"]["verify:packaged-runtime"],
        )
        self.assertEqual("node scripts/clean-packaged-output.js", package["scripts"]["clean:packaged"])
        self.assertIn("backend-manifest.json", package["build"]["files"])
        self.assertEqual("scripts/harden-packaged-backend-acl.js", package["build"]["afterPack"])

    def test_after_pack_hook_hardens_manifest_authority_and_backend_acls(self):
        hook = (ROOT / "ui" / "scripts" / "harden-packaged-backend-acl.js").read_text(encoding="utf-8")

        self.assertIn("hardenPackagedRuntimeAcls", hook)
        self.assertIn("'resources'", hook)
        self.assertIn("'app.asar'", hook)
        self.assertIn("'backend'", hook)
        self.assertIn("'python'", hook)

    def test_packaged_runtime_verifier_uses_manifest_from_packaged_app_bundle(self):
        verifier = (ROOT / "ui" / "scripts" / "verify-packaged-runtime.js").read_text(encoding="utf-8")

        self.assertIn("findPackagedManifestPath", verifier)
        self.assertIn("app.asar", verifier)
        self.assertIn("@electron/asar", verifier)
        self.assertNotIn("manifestPath: path.join(uiRoot, 'backend-manifest.json')", verifier)

    def test_packaged_runtime_verifier_checks_default_python_policy(self):
        verifier = (ROOT / "ui" / "scripts" / "verify-packaged-runtime.js").read_text(encoding="utf-8")

        self.assertIn("assertPackagedPythonPolicy(resourcesRoot)", verifier)
        self.assertIn("assertPackagedPythonWorks(packagedPython, resourcesRoot, backendRoot)", verifier)
        self.assertIn("bundledPythonPath", verifier)
        self.assertIn("python', 'python.exe", verifier)
        self.assertIn("import json, psutil, sys", verifier)
        self.assertIn("import isolator, server", verifier)
        self.assertIn("production packaged runtime accepted arbitrary EII_PYTHON", verifier)

    def test_backend_manifest_generator_emits_deterministic_sha256_schema(self):
        manifest = json.loads((ROOT / "ui" / "backend-manifest.json").read_text(encoding="utf-8"))
        keys = list(manifest["files"].keys())

        self.assertEqual(1, manifest["version"])
        self.assertEqual("sha256", manifest["algorithm"])
        self.assertEqual("1970-01-01T00:00:00.000Z", manifest["generatedAt"])
        self.assertEqual(sorted(keys), keys)
        self.assertTrue(keys)
        for digest in manifest["files"].values():
            self.assertRegex(digest, r"^sha256-[0-9a-f]{64}$")

    def test_release_gate_generates_manifest_and_verifies_packaged_runtime(self):
        release_check = (ROOT / "scripts" / "release-check.ps1").read_text(encoding="utf-8")

        self.assertIn("npm --prefix ui run build:backend-manifest", release_check)
        self.assertIn("git diff --exit-code -- ui/backend-manifest.json", release_check)
        self.assertIn("npm --prefix ui run clean:packaged", release_check)
        self.assertIn("node ui/scripts/clean-packaged-output.js $item", release_check)
        self.assertIn("npm --prefix ui run verify:packaged-runtime", release_check)

    def test_docs_describe_packaged_runtime_provenance_policy(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        building = (ROOT / "BUILDING.md").read_text(encoding="utf-8")
        combined = f"{readme}\n{building}"

        self.assertIn("backend resource integrity manifest", combined)
        self.assertIn("EII_ALLOW_UNTRUSTED_PACKAGED_PYTHON", combined)
        self.assertIn("resources/backend", combined)
        self.assertIn("standard-user writable", combined)
        self.assertIn("trusted app bundle", combined)


if __name__ == "__main__":
    unittest.main()
