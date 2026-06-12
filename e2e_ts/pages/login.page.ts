import { type Locator, type Page } from '@playwright/test';

/**
 * The member sign-in form. Submitting through the real form (not an API
 * shortcut) exercises the hidden CSRF token exactly as a member would —
 * mirrors the `login` helper in functional/conftest.py. `form` (#member-login)
 * is the page container used to assert "we're still on login" after a rejected
 * attempt; `alert` is the flash region.
 */
export class LoginPage {
  readonly form: Locator;
  readonly alert: Locator;

  constructor(private readonly page: Page) {
    this.form = page.locator('#member-login');
    this.alert = page.locator('.alert');
  }

  async goto(): Promise<void> {
    await this.page.goto('/auth/login');
  }

  async login(username: string, password: string): Promise<void> {
    await this.goto();
    await this.page.fill('#username', username);
    await this.page.fill('#password', password);
    await this.page.click('#sign-in-button');
  }
}
