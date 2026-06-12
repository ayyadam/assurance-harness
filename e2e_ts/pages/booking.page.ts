import { type Locator, type Page } from '@playwright/test';

/**
 * The tee-time booking page. Bookable slots are plain `.booking-slot`; full or
 * already-booked ones carry the `booked` class and have no click handler.
 * Mirrors the booking flow in functional/test_member_journey.py.
 */
export class BookingPage {
  readonly confirmButton: Locator;

  constructor(private readonly page: Page) {
    this.confirmButton = page.locator('#confirmBookingBtn');
  }

  async gotoDate(isoDate: string): Promise<void> {
    await this.page.goto(`/member/book-tee-time?date=${isoDate}`);
  }

  firstFreeSlot(): Locator {
    return this.page.locator('.booking-slot:not(.booked)').first();
  }

  async confirm(): Promise<void> {
    await this.confirmButton.click();
  }
}
