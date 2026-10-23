import { useState } from 'react';
import { requestJson } from '../utils/api.mjs';
import { translatedNotice } from '../utils/config.mjs';
import { useI18n } from '../i18n.jsx';

/**
 * Confirmation panel for the engine's "looks like a game" heuristic. The
 * engine only OBSERVES fullscreen/sustained-foreground candidates; nothing is
 * tuned until the user adds a suggestion to the configured games list here.
 *
 * @param {{suggestions: Array<{name: string, pid: number, signals: string[]}> | undefined}} props
 */
export function GameSuggestions({ suggestions }) {
  const { t } = useI18n();
  const [pendingName, setPendingName] = useState(null);
  const [addedNames, setAddedNames] = useState([]);
  const [notice, setNotice] = useState(null);
  const list = Array.isArray(suggestions) ? suggestions : [];
  const visible = list.filter((suggestion) => !addedNames.includes(suggestion.name));
  if (!visible.length && !notice) {
    return null;
  }

  const addToGames = async (name) => {
    setPendingName(name);
    setNotice(null);
    try {
      // Fetch the games list at click time so the append never clobbers
      // edits made in Settings after this page loaded.
      const configPayload = await requestJson('/api/config');
      const games = Array.isArray(configPayload.config?.games) ? [...configPayload.config.games] : [];
      if (!games.includes(name)) {
        games.push(name);
      }
      const result = await requestJson('/api/config', {
        method: 'PUT',
        body: JSON.stringify({ config: { games } })
      });
      setAddedNames((current) => [...current, name]);
      setNotice(result.restart_required
        ? { key: 'suggestions.addedRestart', fallback: '{{game}} added; restart UltraIsolator to apply.', params: { game: name } }
        : { key: 'suggestions.added', fallback: '{{game}} added to your games.', params: { game: name } });
    } catch (error) {
      setNotice({
        key: 'suggestions.saveError',
        fallback: 'Unable to add {{game}}: {{message}}',
        params: { game: name, message: error instanceof Error ? error.message : 'unknown error' }
      });
    } finally {
      setPendingName(null);
    }
  };

  return (
    <section className="game-suggestions" aria-label={t('suggestions.title', 'Looks like a game')}>
      <div className="module-title">{t('suggestions.title', 'Looks like a game')}</div>
      <p className="game-suggestions-detail">
        {t('suggestions.detail', 'These fullscreen apps behaved like games. Nothing changes until you add one to your games list.')}
      </p>
      {visible.length ? (
        <ul className="game-suggestions-list">
          {visible.map((suggestion) => (
            <li className="game-suggestion-item" key={suggestion.name}>
              <span className="game-suggestion-name">{suggestion.name}</span>
              <button
                type="button"
                onClick={() => addToGames(suggestion.name)}
                disabled={Boolean(pendingName)}
              >
                {pendingName === suggestion.name
                  ? t('suggestions.adding', 'Adding')
                  : t('suggestions.add', 'Add to games')}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {notice ? <div className="game-suggestions-notice">{translatedNotice(notice, t)}</div> : null}
    </section>
  );
}
