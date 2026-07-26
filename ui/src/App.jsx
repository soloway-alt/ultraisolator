import { useEffect, useMemo, useState } from 'react';
import {
  Content,
  Header,
  HeaderGlobalBar,
  SideNav,
  SideNavItems,
  SideNavLink
} from '@carbon/react';
import { ErrorBoundary } from './components/ErrorBoundary.jsx';
import { PAGES } from './constants/navigation.js';
import { useLiveSnapshot } from './hooks/useLiveSnapshot.js';
import { DashboardPage } from './pages/Dashboard.jsx';
import { SettingsPage } from './pages/Settings.jsx';
import { TopologyPage } from './pages/Topology.jsx';
import { LogsPage } from './pages/Logs.jsx';
import { AdvancedToolsPage } from './pages/AdvancedTools.jsx';
import { NotificationCenter } from './components/NotificationCenter.jsx';
import { FirstRunWizard } from './components/FirstRunWizard.jsx';
import { I18nProvider, useI18n } from './i18n.jsx';

const PAGE_COMPONENTS = {
  dashboard: DashboardPage,
  settings: SettingsPage,
  topology: TopologyPage,
  logs: LogsPage,
  advanced: AdvancedToolsPage
};

function pageIdFromHash() {
  const pageId = window.location.hash.replace(/^#\/?/, '');
  return PAGES.some((page) => page.id === pageId) ? pageId : 'dashboard';
}

function AppShell() {
  const [activePageId, setActivePageId] = useState(() => pageIdFromHash());
  const live = useLiveSnapshot();
  const { t } = useI18n();
  const activePage = useMemo(
    () => PAGES.find((page) => page.id === activePageId) || PAGES[0],
    [activePageId]
  );
  // PAGE_COMPONENTS covers every id in PAGES; pageIdFromHash falls back to
  // 'dashboard' for unknown hashes, so the lookup can never miss.
  const ActivePage = PAGE_COMPONENTS[activePage.id];

  useEffect(() => {
    const onHashChange = () => setActivePageId(pageIdFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    document.querySelector('.main-content')?.scrollTo({ top: 0, left: 0 });
  }, [activePageId]);

  const navigateToPage = (pageId) => {
    setActivePageId(pageId);
    if (window.location.hash !== `#${pageId}`) {
      window.location.hash = pageId;
    }
  };

  return (
    <div className="app-shell">
      <Header aria-label="UltraIsolator">
        <HeaderGlobalBar>
          <div className="header-status">
            <span className={`stream-dot ${live.connectionState}`} aria-hidden="true" />
            {t(`connection.${live.connectionState}`, live.connectionState)}
          </div>
        </HeaderGlobalBar>
      </Header>

      <SideNav expanded isPersistent aria-label={t('nav.primary', 'Primary navigation')}>
        <SideNavItems>
          {PAGES.map((page) => (
            <SideNavLink
              key={page.id}
              as="button"
              type="button"
              isActive={activePageId === page.id}
              renderIcon={page.renderIcon}
              title={t(page.labelKey, page.label)}
              aria-current={activePageId === page.id ? 'page' : undefined}
              onClick={() => navigateToPage(page.id)}
            >
              {t(page.labelKey, page.label)}
            </SideNavLink>
          ))}
        </SideNavItems>
      </SideNav>

      <ErrorBoundary>
        <Content className="main-content">
          <ActivePage page={activePage} live={live} />
        </Content>
        <NotificationCenter live={live} />
        <FirstRunWizard live={live} />
      </ErrorBoundary>
    </div>
  );
}

function App() {
  return (
    <I18nProvider>
      <AppShell />
    </I18nProvider>
  );
}

export default App;
