import { test, expect } from '../fixtures';
import { HomePage } from '../pages/home.page';

// Public-facing smoke journeys: the site is reachable and the top-level
// navigation renders real pages (not error pages) before the heavier
// authenticated journeys run. Counterpart to functional/test_public_pages.py.
test.describe('Public pages', () => {
  test('home page loads', async ({ page }) => {
    const home = new HomePage(page);
    await home.goto();

    await expect(page).toHaveTitle(/Adam's Golf Club/);
    await expect(home.nav.brand).toBeVisible();
    await expect(home.nav.memberLoginLink).toBeVisible();
  });

  test('top nav reaches public pages', async ({ page }) => {
    const home = new HomePage(page);
    await home.goto();

    // The shared NavBar's brand resolving after each click is a cheap signal
    // that a real page rendered rather than a 500.
    await home.nav.openCourseOverview();
    await expect(page).toHaveURL(/\/course$/);
    await expect(home.nav.brand).toBeVisible();

    await home.nav.openScorecard();
    await expect(page).toHaveURL(/\/course\/scorecard$/);
    await expect(home.nav.brand).toBeVisible();

    await home.nav.openMembership();
    await expect(page).toHaveURL(/\/membership$/);
    await expect(home.nav.brand).toBeVisible();
  });
});
