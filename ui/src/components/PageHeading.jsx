import { useI18n } from '../i18n.jsx';

// The heading derives its text from the PAGES entry (labelKey + fallback), so
// a page cannot ship an untranslated hand-typed title again.
/** @param {{page: import('../types.js').PageEntry, titleId: string, children?: import('react').ReactNode}} props */
export function PageHeading({ page, titleId, children }) {
  const { t } = useI18n();
  return (
    <div className="page-heading">
      <div>
        <div className="section-label">{t('app.brand', 'UltraIsolator')}</div>
        <h1 id={titleId}>{t(page.labelKey, page.title)}</h1>
      </div>
      <div className="status-row">
        {children}
      </div>
    </div>
  );
}
