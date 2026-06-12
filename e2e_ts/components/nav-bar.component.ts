import { type Locator, type Page } from '@playwright/test';

/**
 * The site navigation bar — a shared layout component present on every page,
 * public and authenticated. Modelled as a *component object* rather than
 * duplicated across page objects, because the same navbar appears site-wide:
 * the brand and the public nav links on every page, the user dropdown once
 * signed in. `brand` resolving on any page is the cheap "a real page rendered
 * rather than a 500" signal the public-pages journey relies on.
 */
export class NavBar {
  /** The brand element, present in the shared layout on every page. */
  readonly brand: Locator;
  readonly memberLoginLink: Locator;
  /** The authenticated user dropdown toggle. */
  readonly userMenu: Locator;
  readonly logoutLink: Locator;

  constructor(private readonly page: Page) {
    this.brand = page.locator('#adams-golf-club');
    this.memberLoginLink = page.locator('#member-login-link');
    this.userMenu = page.locator('#user-link');
    this.logoutLink = page.locator('#logout-link');
  }

  async openCourseOverview(): Promise<void> {
    await this.page.click('#course-overview-link');
  }

  async openScorecard(): Promise<void> {
    await this.page.click('#scorecard-link');
  }

  async openMembership(): Promise<void> {
    await this.page.click('#membership-link');
  }

  /** Sign out via the authenticated user dropdown (#user-link → #logout-link). */
  async logout(): Promise<void> {
    await this.userMenu.click();
    await this.logoutLink.click();
  }
}
