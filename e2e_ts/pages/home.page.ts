import { type Locator, type Page } from '@playwright/test';
import { NavBar } from '../components/nav-bar.component';

/**
 * The public landing page, and where the app redirects after logout or an
 * access-denied bounce. Navigation lives on the shared NavBar component; the
 * flash region (`.alert`) is a single element owned by the page.
 */
export class HomePage {
  readonly nav: NavBar;
  readonly alert: Locator;

  constructor(private readonly page: Page) {
    this.nav = new NavBar(page);
    this.alert = page.locator('.alert');
  }

  async goto(): Promise<void> {
    await this.page.goto('/');
  }
}
