import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Tag } from '@carbon/react';
import NotificationIcon from '@carbon/icons-react/es/Notification.js';
import CloseIcon from '@carbon/icons-react/es/Close.js';
import { useI18n } from '../i18n.jsx';
import { useAppSettings } from '../state/AppSettingsContext.jsx';

const TOAST_TTL_MS = 6500;

function severityTagType(severity) {
  if (severity === 'error') {
    return 'red';
  }
  if (severity === 'warning') {
    return 'yellow';
  }
  return 'green';
}

function formatNotificationTime(value, language) {
  if (!value) {
    return '-';
  }
  return new Date(value * 1000).toLocaleTimeString(language === 'ru' ? 'ru-RU' : 'en-US');
}

function notificationText(notification, field, t) {
  const explicitKey = notification?.[`${field}_key`];
  const key = explicitKey || `notification.${notification?.key || notification?.type || 'event'}.${field}`;
  const fallback = notification?.[field] || (field === 'title' ? 'UltraIsolator' : '');
  return t(key, fallback, notification?.data || {});
}

export const NotificationCenter = memo(function NotificationCenter({ notifications: liveNotifications, gameMode }) {
  const { language, t } = useI18n();
  const { settings } = useAppSettings();
  const [open, setOpen] = useState(false);
  const [toastIds, setToastIds] = useState([]);
  const seenToastIds = useRef(new Set());
  const notifications = Array.isArray(liveNotifications) ? liveNotifications : [];
  const toastsEnabled = settings.notificationToastsEnabled !== false;

  useEffect(() => {
    const nextNotification = Array.isArray(liveNotifications) ? liveNotifications[0] : undefined;
    if (!toastsEnabled || gameMode || !nextNotification) {
      return;
    }
    if (
      seenToastIds.current.has(nextNotification.id)
      || (nextNotification.suppress_in_game_mode && gameMode)
    ) {
      return;
    }
    seenToastIds.current.add(nextNotification.id);
    setToastIds((current) => [nextNotification.id, ...current].slice(0, 3));
  }, [gameMode, liveNotifications, toastsEnabled]);

  useEffect(() => {
    if (toastIds.length === 0) {
      return undefined;
    }
    const timers = toastIds.map((id) => window.setTimeout(() => {
      setToastIds((current) => current.filter((toastId) => toastId !== id));
    }, TOAST_TTL_MS));
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [toastIds]);

  const toastNotifications = useMemo(() => {
    const list = Array.isArray(liveNotifications) ? liveNotifications : [];
    const active = new Set(toastIds);
    return list.filter((notification) => active.has(notification.id));
  }, [liveNotifications, toastIds]);

  return (
    <>
      <div className="notification-toast-stack" aria-live="polite">
        {toastNotifications.map((notification) => (
          <section key={notification.id} className={`notification-toast ${notification.severity || 'info'}`}>
            <div className="notification-toast-header">
              <span>{notificationText(notification, 'title', t)}</span>
              <button
                type="button"
                aria-label={t('notifications.dismiss', 'Dismiss notification')}
                onClick={() => setToastIds((current) => current.filter((id) => id !== notification.id))}
              >
                <CloseIcon size={14} />
              </button>
            </div>
            <div className="notification-toast-message">{notificationText(notification, 'message', t)}</div>
          </section>
        ))}
      </div>

      <button
        type="button"
        className={`notification-drawer-toggle${open ? ' open' : ''}`}
        aria-expanded={open}
        aria-label={t('notifications.open', 'Open notification history')}
        aria-controls="notification-history"
        onClick={() => setOpen((current) => !current)}
      >
        <NotificationIcon size={16} />
        <span>{notifications.length}</span>
      </button>

      {open ? (
        <aside className="notification-history-drawer" id="notification-history" aria-label={t('notifications.history', 'Notification history')}>
          <div className="notification-history-header">
            <div>
              <div className="module-title">{t('notifications.title', 'Notifications')}</div>
              <div className="notification-history-subtitle">{t('notifications.sessionHistory', 'Notifications from this session')}</div>
            </div>
            <button type="button" aria-label={t('notifications.close', 'Close notifications')} onClick={() => setOpen(false)}>
              <CloseIcon size={16} />
            </button>
          </div>

          <div className="notification-history-list">
            {notifications.length ? notifications.map((notification) => (
              <article key={notification.id} className={`notification-history-item ${notification.severity || 'info'}`}>
                <div className="notification-history-top">
                  <strong>{notificationText(notification, 'title', t)}</strong>
                  <Tag type={severityTagType(notification.severity)}>{t(`checkStatus.${notification.severity || 'info'}`, notification.severity || 'info')}</Tag>
                </div>
                <div className="notification-history-message">{notificationText(notification, 'message', t)}</div>
                <div className="notification-history-meta">
                  <span>{formatNotificationTime(notification.timestamp, language)}</span>
                  {notification.suppress_in_game_mode ? <span>{t('notifications.quietDuringGame', 'Quiet during gameplay')}</span> : null}
                </div>
              </article>
            )) : (
              <div className="module-empty">{t('notifications.empty', 'No notifications in this session')}</div>
            )}
          </div>
        </aside>
      ) : null}
    </>
  );
});
