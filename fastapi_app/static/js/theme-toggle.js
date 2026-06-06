const themeToggleButton = document.querySelector('.theme-toggle');
const themeStorageKey = 'artstudio-theme';
const rootElement = document.documentElement;

const getStoredTheme = () => localStorage.getItem(themeStorageKey);
const getPreferredTheme = () => (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

const setTheme = (theme) => {
  if (!rootElement) return;
  rootElement.setAttribute('data-theme', theme);
  if (document.body) {
    document.body.setAttribute('data-theme', theme);
  }
  localStorage.setItem(themeStorageKey, theme);

  const themeIcon = themeToggleButton?.querySelector('i');
  const themeLabel = themeToggleButton?.querySelector('.theme-toggle-label');
  if (themeIcon) {
    themeIcon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
  }

  if (themeLabel) {
    themeLabel.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
  }
};

const getInitialTheme = () => {
  const savedTheme = getStoredTheme();
  return savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : getPreferredTheme();
};

window.addEventListener('DOMContentLoaded', () => {
  if (!themeToggleButton) return;

  setTheme(getInitialTheme());

  themeToggleButton.addEventListener('click', () => {
    const currentTheme = rootElement.dataset.theme || 'light';
    setTheme(currentTheme === 'dark' ? 'light' : 'dark');
  });
});
