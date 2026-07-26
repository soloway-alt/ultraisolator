import React from 'react';
import { createRoot } from 'react-dom/client';
import './carbon.scss';
import './styles.css';
import App from './App.jsx';
import { AppSettingsProvider } from './state/AppSettingsContext.jsx';

createRoot(document.getElementById('root')).render(
  <AppSettingsProvider>
    <React.StrictMode>
      <App />
    </React.StrictMode>
  </AppSettingsProvider>
);
