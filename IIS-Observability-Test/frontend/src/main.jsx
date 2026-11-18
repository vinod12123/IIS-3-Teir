import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './stockroom.css';
import './control-auth.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
