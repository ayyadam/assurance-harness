import { test, expect } from '../fixtures';
import { LoginPage } from '../pages/login.page';
import { BookingPage } from '../pages/booking.page';
import { MemberDashboardPage } from '../pages/member-dashboard.page';
import { HomePage } from '../pages/home.page';

// The headline end-to-end evidence for the functional layer: a member signs in,
// books a tee time through the real browser flow (JS slot selection + the
// CSRF-protected form), and signs out. The TypeScript counterpart to
// functional/test_member_journey.py.
test.describe('Member journey', () => {
  test('login succeeds and lands on the dashboard', async ({ page, member }) => {
    await new LoginPage(page).login(member.username, member.password);

    const dashboard = new MemberDashboardPage(page);
    await expect(page).toHaveURL(/\/member\/dashboard/);
    await expect(dashboard.container).toBeVisible();
    await expect(dashboard.alert).toContainText(`Welcome back, ${member.firstName}`);
  });

  test('login rejects a bad password', async ({ page, member }) => {
    const loginPage = new LoginPage(page);
    await loginPage.login(member.username, 'definitely-wrong');

    // No redirect: the login page re-renders with an error and no session.
    await expect(loginPage.form).toBeVisible();
    await expect(loginPage.alert).toContainText('Invalid username or password');
  });

  test('member books a tee time', async ({ memberPage: page }) => {
    // Book two days out so a full slate of slots exists regardless of the time
    // of day the suite runs.
    const d = new Date();
    d.setDate(d.getDate() + 2);
    const bookingDate = d.toISOString().slice(0, 10);

    const booking = new BookingPage(page);
    await booking.gotoDate(bookingDate);

    const slot = booking.firstFreeSlot();
    await expect(slot).toBeVisible();
    await slot.click();

    await expect(booking.confirmButton).toBeVisible();
    await booking.confirm();

    // waitForURL (not expect.toHaveURL) after a navigating click: explicit
    // intent, and immune to cold-runner spikes in the confirm POST → commit →
    // 302 → dashboard GET chain (R-018).
    await page.waitForURL(/\/member\/dashboard/);
    await expect(new MemberDashboardPage(page).alert).toContainText(
      'Tee time booked successfully',
    );
  });

  test('member can log out', async ({ memberPage: page }) => {
    await new MemberDashboardPage(page).nav.logout();

    // Host-agnostic (G1-ready): assert the path is the site root rather than
    // hard-coding the host, so this survives a base-URL change.
    expect(new URL(page.url()).pathname).toBe('/');

    const home = new HomePage(page);
    await expect(home.alert).toContainText('You have been logged out');
    await expect(home.nav.memberLoginLink).toBeVisible();
  });
});
