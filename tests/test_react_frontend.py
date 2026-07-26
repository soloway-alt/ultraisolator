import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
SRC = UI / "src"


class ReactFrontendContractTests(unittest.TestCase):
    def test_vite_react_entrypoints_exist(self):
        self.assertTrue((UI / "index.html").exists())
        self.assertTrue((SRC / "main.jsx").exists())
        self.assertTrue((SRC / "App.jsx").exists())
        self.assertTrue((SRC / "styles.css").exists())
        self.assertTrue((SRC / "premium.css").exists())

        entry = (SRC / "main.jsx").read_text(encoding="utf-8")
        self.assertLess(entry.index("./styles.css"), entry.index("./premium.css"))

    def test_package_declares_carbon_renderer_stack(self):
        package = json.loads((UI / "package.json").read_text(encoding="utf-8"))

        self.assertIn("@carbon/react", package["dependencies"])
        self.assertIn("@carbon/icons-react", package["dependencies"])
        self.assertIn("sass", package["devDependencies"])
        for group_name in ("dependencies", "devDependencies"):
            for name, version in package[group_name].items():
                self.assertNotRegex(version, r"^[~^>=<*]", f"{name} should be pinned")

    def test_layout_has_sidebar_navigation_and_page_registry(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")

        self.assertIn("Dashboard", app)
        self.assertIn("Settings", app)
        self.assertIn("Topology", app)
        self.assertIn("SideNav", app)
        self.assertIn("useLiveSnapshot", app)
        # Every navigable page id must resolve to a real component; the
        # Placeholder fallback was removed once PAGE_COMPONENTS covered PAGES.
        self.assertIn("PAGE_COMPONENTS[activePage.id]", app)
        self.assertNotIn("Placeholder", app)

    def test_renderer_is_split_into_pages_components_constants_and_utils(self):
        expected_files = (
            "constants/navigation.js",
            "constants/processes.js",
            "constants/settings.js",
            "constants/topology.js",
            "components/ErrorBoundary.jsx",
            "components/KpiCell.jsx",
            "components/PageHeading.jsx",
            "components/StatusTag.jsx",
            "pages/Dashboard.jsx",
            "pages/Settings.jsx",
            "pages/Topology.jsx",
            "utils/appSettings.js",
            "utils/config.js",
            "utils/format.js",
            "utils/lifecycle.js",
            "utils/topology.js",
        )
        for relative_path in expected_files:
            with self.subTest(path=relative_path):
                self.assertTrue((SRC / relative_path).exists(), f"{relative_path} is missing")

        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        self.assertLess(len(app.splitlines()), 180)
        for component_name in ("DashboardPage", "SettingsPage", "TopologyPage", "ProcessTable", "ConfigField"):
            self.assertNotIn(f"function {component_name}", app)
        self.assertIn("from './pages/Dashboard.jsx'", app)
        self.assertIn("from './pages/Settings.jsx'", app)
        self.assertIn("from './pages/Topology.jsx'", app)
        self.assertIn("from './components/ErrorBoundary.jsx'", app)

    def test_dashboard_has_live_kpi_status_panel_and_quick_actions(self):
        dashboard = (SRC / "pages" / "Dashboard.jsx").read_text(encoding="utf-8")
        lifecycle = (SRC / "utils" / "lifecycle.js").read_text(encoding="utf-8")

        self.assertIn("function DashboardPage", dashboard)
        self.assertIn("dashboard-status-panel", dashboard)
        self.assertIn("active_games", dashboard)
        self.assertIn("monitoring_active", dashboard)
        self.assertIn("tuning_state", dashboard)
        self.assertIn("Admin", dashboard)
        self.assertIn("Power Plan", dashboard)
        self.assertIn("Timer", dashboard)
        self.assertIn("CPU allocation", dashboard)
        self.assertIn("Compatibility", dashboard)
        self.assertIn("Resume monitoring", dashboard)
        self.assertIn("Pause monitoring", dashboard)
        self.assertIn("Restore Windows settings", dashboard)
        self.assertIn("actionableCapabilityIssues", dashboard)
        self.assertIn("issue.severity === 'warning'", dashboard)
        self.assertIn("issue.severity === 'error'", dashboard)
        self.assertIn("postLifecycleAction", dashboard)
        self.assertIn("dashboard-profile-hero", dashboard)
        self.assertIn("planned-change-summary", dashboard)
        self.assertIn("dashboard-trust-strip", dashboard)
        self.assertIn("dashboard-primary-action", dashboard)
        self.assertNotIn("setInterval", dashboard)
        self.assertIn("requestJson", lifecycle)
        self.assertNotIn("CPU/RAM", dashboard)

    def test_dashboard_has_process_table_filters_and_columns(self):
        table = (SRC / "components" / "ProcessTable.jsx").read_text(encoding="utf-8")
        process_constants = (SRC / "constants" / "processes.js").read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function ProcessTable", table)
        self.assertIn("process-filter-bar", table)
        self.assertIn("Search PID or application", table)
        for label in ("All", "Background limited", "Game", "Left unchanged"):
            self.assertIn(label, table + process_constants)
        for column in ("Action", "Application", "PID", "Priority", "CPU allocation", "Why it matters"):
            self.assertIn(column, table)
        for tuning_state in ("pending", "applied", "skipped", "blocked", "failed"):
            self.assertIn(f"process.reason.game.{tuning_state}", (SRC / "locales" / "en.mjs").read_text(encoding="utf-8"))
        self.assertIn("process.tuning_state", table)
        self.assertIn("observed_game", table)
        self.assertNotIn("process.column.threads", table)
        self.assertNotIn("process.column.gen", table)
        self.assertIn("useMemo", table)
        self.assertIn(".process-table", styles)
        self.assertIn(".status-badge", styles)
        self.assertNotIn("setInterval", table)

    def test_settings_has_config_editor_and_app_settings(self):
        settings = (SRC / "pages" / "Settings.jsx").read_text(encoding="utf-8")
        settings_constants = (SRC / "constants" / "settings.js").read_text(encoding="utf-8")
        app_settings = (SRC / "utils" / "appSettings.js").read_text(encoding="utf-8")
        config_utils = (SRC / "utils" / "config.js").read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function SettingsPage", settings)
        self.assertIn("/api/config/defaults", settings)
        self.assertIn("/api/config", settings)
        self.assertIn("validateConfigDraft", settings)
        for section in (
            "Games & libraries",
            "Background isolation",
            "Detection & recovery",
            "Game tuning",
            "For specialists",
            "App behavior",
        ):
            self.assertIn(section, settings + settings_constants)
        for field in (
            "games",
            "auto_detect_steam_games",
            "auto_detect_epic_games",
            "steam_library_paths",
            "epic_library_paths",
            "enable_background_jailing",
            "maintenance_jail_batch_size",
            "maintenance_jail_interval_ms",
            "maintenance_jail_batch_cooldown_ms",
            "maintenance_skip_after_quiet_cycles",
            "poll_interval_active_ms",
            "poll_interval_idle_ms",
            "housekeeping_cores",
            "disable_power_scheme_switch",
            "disable_timer_resolution_tweak",
            "disable_game_priority_boost",
            "game_close_debounce_s",
            "game_exit_restore_delay_s",
            "gc_full_collect_interval_s",
            "anti_cheat_mode",
            "protected_extra",
            "log_file",
            "event_backend",
            "allow_mmcss_injection",
        ):
            self.assertIn(field, settings + settings_constants)
        for label in (
            "Launch at Windows startup",
            "Minimize to tray on start",
            "Show notification toasts",
            "Save",
            "Reset",
            "Reload",
        ):
            self.assertIn(label, settings)
        self.assertNotIn("Start isolator automatically", settings + settings_constants)
        self.assertNotIn("startIsolatorAutomatically", settings + settings_constants + app_settings)
        self.assertIn("POSITIVE_BOOLEAN_FIELDS", settings_constants)
        self.assertIn("window.isolator?.getAppSettings", app_settings)
        self.assertIn("window.isolator?.updateAppSettings", app_settings)
        self.assertIn("validateConfigDraft", config_utils)
        self.assertIn(".settings-grid", styles)
        self.assertIn(".settings-field", styles)
        self.assertIn(".toggle-row", styles)

    def test_app_settings_have_one_revision_aware_root_provider(self):
        main = (SRC / "main.jsx").read_text(encoding="utf-8")
        context = (SRC / "state" / "AppSettingsContext.jsx").read_text(encoding="utf-8")
        store = (SRC / "state" / "AppSettingsStore.mjs").read_text(encoding="utf-8")
        i18n = (SRC / "i18n.jsx").read_text(encoding="utf-8")
        renderer = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.jsx"))

        self.assertIn("<AppSettingsProvider>", main)
        self.assertIn("useSyncExternalStore", context)
        self.assertIn("new AppSettingsStore", context)
        self.assertIn("writeQueue", store)
        self.assertIn("localRevision", store)
        self.assertIn("useAppSettings", i18n)
        self.assertNotIn("app-settings-updated", renderer)
        self.assertNotIn("window.addEventListener('app-settings", renderer)

    def test_settings_has_per_app_profiles_crud_editor(self):
        settings = (SRC / "pages" / "Settings.jsx").read_text(encoding="utf-8")
        config_utils = (SRC / "utils" / "config.js").read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("App-specific rules", settings)
        self.assertIn("addProfile", settings)
        self.assertIn("removeProfile", settings)
        self.assertIn("updateProfile", settings)
        self.assertIn("Application executable", settings)
        for label in ("Treat as game", "Always leave unchanged", "Always limit in background", "Priority"):
            self.assertIn(label, settings)
        self.assertIn("app_profiles", settings + config_utils)
        self.assertIn("validateAppProfilesDraft", config_utils)
        self.assertIn(".profiles-editor", styles)

    def test_first_run_wizard_applies_presets_and_tracks_completion(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        constants = (SRC / "constants" / "settings.js").read_text(encoding="utf-8")
        app_settings = (SRC / "state" / "AppSettingsContext.jsx").read_text(encoding="utf-8")
        wizard_path = SRC / "components" / "FirstRunWizard.jsx"
        self.assertTrue(wizard_path.exists())
        wizard = wizard_path.read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("FirstRunWizard", app)
        self.assertIn("firstRunCompleted", constants + app_settings + wizard)
        self.assertIn("CONFIG_PRESETS", constants)
        for label in ("Competitive", "Casual", "Streaming"):
            self.assertIn(label, constants + wizard)
        self.assertIn("/api/config", wizard)
        self.assertIn("useAppSettings", wizard)
        self.assertIn("updateSettings", wizard)
        self.assertIn("first-run-overlay", wizard)
        self.assertIn("STEP_COUNT = 3", wizard)
        self.assertIn("prepareReview", wizard)
        self.assertIn("reviewConfig", wizard)
        self.assertIn("configApplied", wizard)
        self.assertIn("firstRun.completionError", wizard)
        self.assertIn("aria-busy", wizard)
        self.assertIn("persistent_recovery_incomplete", wizard)
        self.assertIn("reported_failure_count", wizard)
        for field in ("maintenance_jail_batch_size", "maintenance_jail_interval_ms", "maintenance_jail_batch_cooldown_ms"):
            self.assertIn(field, wizard)
        self.assertNotIn("Local engine", wizard)
        self.assertNotIn("Jail batch size", wizard)
        self.assertLess(wizard.index("...defaultsPayload.defaults"), wizard.index("...configPayload.config"))
        self.assertLess(wizard.index("...configPayload.config"), wizard.index("...selectedPreset.config"))
        self.assertIn("aria-describedby", wizard)
        self.assertIn(".first-run-overlay", styles)

    def test_settings_can_apply_config_presets_after_first_run(self):
        settings = (SRC / "pages" / "Settings.jsx").read_text(encoding="utf-8")
        constants = (SRC / "constants" / "settings.js").read_text(encoding="utf-8")

        self.assertIn("Session profiles", settings)
        self.assertIn("applyPresetToDraft", settings)
        self.assertIn("CONFIG_PRESETS", settings + constants)
        for label in ("Competitive", "Casual", "Streaming"):
            self.assertIn(label, settings + constants)

    def test_settings_reset_requires_confirmation(self):
        settings = (SRC / "pages" / "Settings.jsx").read_text(encoding="utf-8")
        reset_body = settings[settings.index("const resetToDefaults = () => {"):settings.index("const saveSettings = async")]

        self.assertIn("window.confirm", reset_body)
        self.assertLess(reset_body.index("window.confirm"), reset_body.index("setDraft("))

    def test_topology_has_cpu_map_summary_and_core_details(self):
        topology = (SRC / "pages" / "Topology.jsx").read_text(encoding="utf-8")
        topology_utils = (SRC / "utils" / "topology.js").read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function TopologyPage", topology)
        self.assertIn("/api/topology", topology)
        self.assertIn("refresh=1", topology)
        self.assertIn("groupCoresByLlc", topology)
        self.assertIn("function groupCoresByLlc", topology_utils)
        self.assertIn("selectedCore", topology)
        for label in ("CPU Map", "Total Cores", "Game", "Background", "Housekeeping", "LLC", "P-core", "E-core", "Parked"):
            self.assertIn(label, topology)
        self.assertIn("partition-game", topology)
        self.assertIn("partition-background", topology)
        self.assertIn("partition-housekeeping", topology)
        self.assertIn("core-tile", topology)
        self.assertIn(".topology-map", styles)
        self.assertIn(".llc-group", styles)
        self.assertIn(".core-tile", styles)
        self.assertIn(".core-detail-panel", styles)

    def test_logs_page_has_log_viewer_filters_and_game_mode_pause(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        navigation = (SRC / "constants" / "navigation.js").read_text(encoding="utf-8")
        logs_path = SRC / "pages" / "Logs.jsx"
        self.assertTrue(logs_path.exists())
        logs = logs_path.read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("LogsPage", app)
        self.assertIn("from './pages/Logs.jsx'", app)
        self.assertIn("Activity", navigation)
        self.assertIn("id: 'logs'", navigation)
        self.assertIn("/api/logs", logs)
        self.assertIn("setInterval", logs)
        self.assertIn("game_mode", logs)
        self.assertIn("Log refresh paused during game mode", logs)
        self.assertIn("Search logs", logs)
        self.assertIn("All categories", logs)
        for label in ("All", "INFO", "WARN", "ERROR"):
            self.assertIn(label, logs)
        self.assertIn(".logs-page", styles)
        self.assertIn(".log-table", styles)

    def test_advanced_tools_has_readonly_msi_viewer(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        navigation = (SRC / "constants" / "navigation.js").read_text(encoding="utf-8")
        tools_path = SRC / "pages" / "AdvancedTools.jsx"
        self.assertTrue(tools_path.exists())
        tools = tools_path.read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("AdvancedToolsPage", app)
        self.assertIn("Advanced", navigation)
        self.assertIn("id: 'advanced'", navigation)
        self.assertIn("Message Signaled Interrupts", tools)
        self.assertIn("/api/msi", tools)
        self.assertIn("readonly", tools.lower())
        self.assertIn("Restart required", tools)
        self.assertIn("paused during game mode", tools)
        self.assertIn("msi-table", tools)
        self.assertIn(".advanced-tools-page", styles)
        self.assertIn(".msi-table", styles)

    def test_app_has_memory_only_notification_toasts_and_history_drawer(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        hook_path = SRC / "hooks" / "useLiveSnapshot.js"
        center_path = SRC / "components" / "NotificationCenter.jsx"
        self.assertTrue(center_path.exists())
        hook = hook_path.read_text(encoding="utf-8")
        center = center_path.read_text(encoding="utf-8")
        settings = (SRC / "pages" / "Settings.jsx").read_text(encoding="utf-8")
        app_settings = (SRC / "constants" / "settings.js").read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("NotificationCenter", app)
        self.assertIn("eventName === 'notification'", hook)
        self.assertIn("malformed notification frame", hook)
        self.assertIn("notifications", hook)
        self.assertIn("notification-history-drawer", center)
        self.assertIn("notification-toast-stack", center)
        self.assertIn("suppress_in_game_mode", center)
        self.assertIn("App behavior", settings)
        self.assertIn("Show notification toasts", settings)
        self.assertIn("notificationToastsEnabled", app_settings)
        self.assertIn("notificationText", center)
        self.assertIn("notification?.data", center)
        self.assertNotIn("<span>{notification.type}</span>", center)
        self.assertIn(".notification-toast-stack", styles)
        self.assertIn(".notification-history-drawer", styles)

    def test_dashboard_has_system_analysis_widget(self):
        dashboard = (SRC / "pages" / "Dashboard.jsx").read_text(encoding="utf-8")
        analysis_path = SRC / "components" / "SystemAnalysis.jsx"
        self.assertTrue(analysis_path.exists())
        analysis = analysis_path.read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        # Dashboard is the consumer; App.jsx routes pages and must not carry
        # a direct SystemAnalysis import.
        self.assertIn("SystemAnalysis", dashboard)
        self.assertIn("from '../components/SystemAnalysis.jsx'", dashboard)
        self.assertIn("/api/analysis", analysis)
        self.assertIn("Setup quality", analysis)
        self.assertIn("Setup score", analysis)
        self.assertIn("Ready checks", analysis)
        self.assertNotIn("Boost Potential", analysis)
        self.assertNotIn("GPU bottleneck", analysis)
        self.assertNotIn("MVP", analysis)
        self.assertIn("game_mode", analysis)
        self.assertIn("paused", analysis)
        self.assertIn(".analysis-panel", styles)
        self.assertIn(".analysis-score", styles)

    def test_dashboard_has_game_readiness_checklist_widget(self):
        dashboard = (SRC / "pages" / "Dashboard.jsx").read_text(encoding="utf-8")
        readiness_path = SRC / "components" / "ReadinessChecklist.jsx"
        self.assertTrue(readiness_path.exists())
        readiness = readiness_path.read_text(encoding="utf-8")
        locale = (SRC / "locales" / "en.mjs").read_text(encoding="utf-8")
        styles = (SRC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("ReadinessChecklist", dashboard)
        self.assertIn("/api/readiness", readiness)
        self.assertIn("Game readiness", readiness)
        self.assertIn("paused during game mode", readiness)
        for label in ("Automatic performance mode", "Low-latency timer", "Background load control", "Game priority boost"):
            self.assertIn(label, readiness + locale)
        self.assertIn("configured_games", readiness)
        self.assertNotIn("cacheHit", readiness)
        self.assertNotIn("cacheFresh", readiness)
        self.assertIn(".readiness-panel", styles)
        self.assertIn(".readiness-check", styles)

    def test_app_wraps_main_content_in_error_boundary(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        boundary = (SRC / "components" / "ErrorBoundary.jsx").read_text(encoding="utf-8")

        self.assertIn("class ErrorBoundary", boundary)
        self.assertIn("componentDidCatch", boundary)
        self.assertIn("Something went wrong", boundary)
        self.assertIn("window.location.reload()", boundary)
        self.assertIn("<ErrorBoundary>", app)
        self.assertIn("</ErrorBoundary>", app)

    def test_live_hook_uses_lazy_sse_only_when_visible(self):
        hook = (SRC / "hooks" / "useLiveSnapshot.js").read_text(encoding="utf-8")

        self.assertIn("window.isolator?.startLiveSnapshot", hook)
        self.assertIn("window.isolator?.stopLiveSnapshot", hook)
        self.assertIn("window.isolator?.onLiveSnapshot", hook)
        self.assertIn("document.visibilityState === 'visible'", hook)
        self.assertIn("visibilitychange", hook)
        self.assertNotIn("fetch(", hook)
        self.assertNotIn("/api/live", hook)
        self.assertNotIn("Authorization", hook)
        self.assertNotIn("resolveBackendUrl", hook)
        self.assertNotIn("resolveBackendToken", hook)
        self.assertNotIn("setInterval", hook)
        self.assertNotIn("/api/status", hook)

    def test_config_validation_rejects_blank_numeric_fields(self):
        config_utils = (SRC / "utils" / "config.js").read_text(encoding="utf-8")

        self.assertIn("is required", config_utils)
        self.assertIn("if (!text)", config_utils)
        self.assertNotIn("Number(String(value).trim())", config_utils)

    def test_backend_requests_use_preload_proxy_without_renderer_secrets(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        hook = (SRC / "hooks" / "useLiveSnapshot.js").read_text(encoding="utf-8")
        settings = (SRC / "pages" / "Settings.jsx").read_text(encoding="utf-8")
        topology = (SRC / "pages" / "Topology.jsx").read_text(encoding="utf-8")
        api_path = SRC / "utils" / "api.js"
        self.assertTrue(api_path.exists())
        api = api_path.read_text(encoding="utf-8")

        self.assertIn("export async function requestJson", api)
        self.assertIn("window.isolator?.backendRequest", api)
        self.assertIn("function operationForRequest", api)
        self.assertIn("backend proxy is unavailable", api)
        self.assertNotIn("fetch(", api)
        self.assertNotIn("DEFAULT_BACKEND_URL", api)
        self.assertNotIn("VITE_API_BASE_URL", api)
        self.assertNotIn("getBackendUrl", api)
        self.assertNotIn("getBackendToken", api)
        self.assertNotIn("VITE_API_TOKEN", api)
        self.assertNotIn("Authorization", api)
        self.assertNotIn("Bearer", api)
        self.assertNotIn("resolveBackendUrl", app)
        self.assertNotIn("resolveBackendUrl", hook)
        self.assertNotIn("resolveBackendToken", hook)
        self.assertNotIn("from '../utils/api.js'", hook)
        self.assertIn("from '../utils/api.js'", settings)
        self.assertIn("from '../utils/api.js'", topology)

    def test_locales_are_split_and_primary_copy_uses_plain_language(self):
        i18n = (SRC / "i18n.jsx").read_text(encoding="utf-8")
        english = (SRC / "locales" / "en.mjs").read_text(encoding="utf-8")
        russian = (SRC / "locales" / "ru.mjs").read_text(encoding="utf-8")

        self.assertIn("assertLocaleParity", i18n)
        self.assertIn("document.documentElement.lang = language", i18n)
        self.assertIn("from './locales/en.mjs'", i18n)
        self.assertIn("from './locales/ru.mjs'", i18n)
        for obsolete in ("Boost Potential", "GPU bottleneck", "MVP", "Recovery backlog", "Start isolator automatically"):
            self.assertNotIn(obsolete, english)
        for obsolete in ("Потенциал буста", "Упор в GPU", "MVP", "Recovery backlog", "Автоматически запускать isolator"):
            self.assertNotIn(obsolete, russian)
        self.assertIn("'dashboard.compatibility': 'Compatibility'", english)
        self.assertIn("'dashboard.compatibility': 'Совместимость'", russian)

    def test_selected_premium_theme_is_loaded_after_legacy_styles(self):
        styles = (SRC / "premium.css").read_text(encoding="utf-8")
        legacy_styles = (SRC / "styles.css").read_text(encoding="utf-8")

        for token in ("#07111c", "#0e1a28", "#2f7ef7", "#35d392", "JetBrains Mono", "Inter"):
            self.assertIn(token, styles)
        for selector in (".dashboard-profile-hero", ".dashboard-trust-strip", ".first-run-review", ".kpi-cell"):
            self.assertIn(selector, styles)
        self.assertIn("--eii-accent", styles)
        self.assertIn(".toggle-row > .toggle-control", styles)
        self.assertIn(".toggle-row > .toggle-control > input:focus-visible", styles)
        self.assertIn("@container (max-width: 460px)", styles)
        self.assertIn("@media (max-width: 1320px)", styles)
        self.assertIn("@media (max-width: 1180px)", styles)
        self.assertIn("margin-left: 64px !important", styles)
        self.assertIn(".cds--side-nav__overlay-active", styles)
        self.assertIn(".dashboard-insights", styles)
        self.assertIn("repeat(auto-fit, minmax(640px, 1fr))", styles)
        self.assertIn(".cds--tile.settings-section.presets-section", styles)
        self.assertIn(".cds--tile.settings-section.app-behavior-section", styles)
        self.assertIn(".settings-section.section-detection", styles)
        self.assertIn(".settings-section.section-tuning", styles)
        self.assertIn(".dashboard-kpi-grid", styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", styles)
        self.assertNotIn("gradient(", styles.lower())
        for stylesheet in (legacy_styles, styles):
            self.assertNotRegex(stylesheet, r"\.toggle-row\s+input")
        self.assertIn(".settings-field > input", legacy_styles)
        self.assertNotIn(".settings-field input", legacy_styles)

    def test_public_text_has_no_mojibake_artifacts(self):
        checked_files = (
            ROOT / "README.md",
            ROOT / "BUILDING.md",
            ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md",
            SRC / "i18n.jsx",
        )
        mojibake_markers = ("Ð", "Ñ", "â€”", "â€“", "â”")

        for path in checked_files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for marker in mojibake_markers:
                    self.assertNotIn(marker, text)

    def test_repository_has_oss_launch_hygiene_files(self):
        expected_files = (
            ROOT / "docs" / "oss-launch-checklist.md",
            ROOT / "docs" / "release-readiness.md",
            ROOT / "docs" / "release-notes-template.md",
            ROOT / "scripts" / "release-check.ps1",
            ROOT / "scripts" / "release-manifest.ps1",
            ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml",
            ROOT / ".github" / "ISSUE_TEMPLATE" / "benchmark_report.md",
            ROOT / ".github" / "pull_request_template.md",
        )
        for path in expected_files:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"{path} is missing")

        launch = (ROOT / "docs" / "oss-launch-checklist.md").read_text(encoding="utf-8")
        self.assertIn("Do not buy stars", launch)
        self.assertIn("Codex for OSS", launch)

        readiness = (ROOT / "docs" / "release-readiness.md").read_text(encoding="utf-8")
        self.assertIn("Hypotheses and Tests", readiness)
        self.assertIn("Production Go / No-Go", readiness)

        release_check = (ROOT / "scripts" / "release-check.ps1").read_text(encoding="utf-8")
        for command in (
            "python -m unittest discover",
            "python best_isolator.py --dry-run",
            "npm --prefix ui audit",
            "npm --prefix ui run smoke",
            "npm --prefix ui run build",
            "npm --prefix ui run clean:packaged",
            "scripts/release-manifest.ps1",
            "git check-ignore",
            "node ui/scripts/clean-packaged-output.js $item",
        ):
            self.assertIn(command, release_check)

        manifest_script = (ROOT / "scripts" / "release-manifest.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-FileHash -Algorithm SHA256", manifest_script)
        self.assertIn("SHA256SUMS.txt", manifest_script)

        release_notes = (ROOT / "docs" / "release-notes-template.md").read_text(encoding="utf-8")
        self.assertIn("SHA256SUMS.txt", release_notes)
        self.assertIn("not code-signed", release_notes)


if __name__ == "__main__":
    unittest.main()
