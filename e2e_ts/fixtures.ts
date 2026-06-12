import { test as base, expect, type Page } from '@playwright/test';
import { LoginPage } from './pages/login.page';

export type Credentials = {
  username: string;
  password: string;
  firstName: string;
};

type Fixtures = {
  member: Credentials;
  login: (page: Page, username: string, password: string) => Promise<void>;
  memberPage: Page;
};

/**
 * The TypeScript counterpart to functional/conftest.py. Provides the same
 * cross-cutting concerns as pytest fixtures: seeded credentials, a login
 * helper, an already-authenticated member page, and the R-018 scroll shim.
 */
export const test = base.extend<Fixtures>({
  // R-018 mitigation (mirrors functional/conftest.py, F-012 / F-025). The
  // booking page calls scrollIntoView({behavior:'smooth'}) on the wrapper
  // holding the confirm button; on a cold runner the confirm click races the
  // animation and is lost. Two layers, because they cover different code paths:
  //   1. scroll-behavior:auto on the root — kills CSS-driven smooth scroll.
  //   2. a scrollIntoView shim coercing behavior:'auto' — kills calls passing
  //      behavior:'smooth' EXPLICITLY (CSS does not override an explicit arg).
  // The real submit button, form, and handler are still exercised; only the
  // cosmetic transition is bypassed.
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      document.documentElement.style.scrollBehavior = 'auto';
      const orig = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (
        arg?: boolean | ScrollIntoViewOptions,
      ) {
        if (arg && typeof arg === 'object') {
          return orig.call(this, { ...arg, behavior: 'auto' });
        }
        return orig.call(this, arg);
      };
    });
    await use(page);
  },

  // A seeded non-admin member (see golf-web-app/seed.py). Credentials are
  // env-driven (G1-ready) with defaults matching the Python suite.
  member: async ({}, use) => {
    await use({
      username: process.env.SUT_USERNAME ?? 'john.smith',
      password: process.env.SUT_PASSWORD ?? 'Password1',
      firstName: 'John',
    });
  },

  login: async ({}, use) => {
    await use(async (page, username, password) => {
      await new LoginPage(page).login(username, password);
    });
  },

  // A page already authenticated as the seeded member.
  memberPage: async ({ page, login, member }, use) => {
    await login(page, member.username, member.password);
    await page.waitForURL(/\/member\/dashboard/);
    await use(page);
  },
});

export { expect };
