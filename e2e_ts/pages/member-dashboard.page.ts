import { type Locator, type Page } from '@playwright/test';
import { NavBar } from '../components/nav-bar.component';

/**
 * The authenticated member dashboard — the landing page after login and after a
 * successful booking. Logout lives on the shared NavBar component; `alert` is
 * the flash region (welcome message, booking confirmation).
 */
export class MemberDashboardPage {
  readonly nav: NavBar;
  readonly container: Locator;
  readonly alert: Locator;

  constructor(private readonly page: Page) {
    this.nav = new NavBar(page);
    this.container = page.locator('#member-dashboard');
    this.alert = page.locator('.alert');
  }
}
