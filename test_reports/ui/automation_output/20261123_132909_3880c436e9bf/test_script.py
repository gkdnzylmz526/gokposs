async def run_test(page, output_dir, page_url):
    import asyncio

    try:
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_selector('[data-testid="metric-bugünkü-ciro"]', timeout=10000)
        print('PASS: dashboard loaded on mobile')
        nav_count = await page.locator('nav [data-testid^="nav-"]').count()
        if nav_count >= 7:
            print(f'PASS: mobile navigation exposes {nav_count} management links')
        else:
            print(f'FINDING: mobile navigation exposes only {nav_count} links')
        overflow = await page.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth')
        if overflow:
            print('FINDING: mobile page has horizontal overflow')
        else:
            print('PASS: no mobile horizontal overflow')
        await page.locator('[data-testid="nav-cash"]').scroll_into_view_if_needed()
        await page.locator('[data-testid="nav-cash"]').click()
        await page.wait_for_selector('[data-testid="add-cash-button"]', timeout=5000)
        await page.locator('[data-testid="add-cash-button"]').scroll_into_view_if_needed()
        await page.locator('[data-testid="add-cash-button"]').click()
        title = (await page.locator('[data-testid="entry-modal"] h2').inner_text()).strip()
        if title:
            print(f'PASS: cash modal title is {title!r}')
        else:
            print('FINDING: cash modal title is empty')
        await page.locator('[data-testid="close-modal-button"]').click()

        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.locator('[data-testid="nav-sales"]').click()
        await page.locator('[data-testid="add-sales-button"]').click()
        await page.fill('[data-testid="amount-field"] input', '250')
        await page.fill('[data-testid="channel-field"] input', 'TEST_Salon')
        await page.fill('[data-testid="note-field"] input', 'TEST_UI satış')
        await page.locator('[data-testid="save-entry-button"]').click()
        await page.wait_for_timeout(700)
        if await page.locator('[data-testid="entry-modal"]').count() == 0:
            print('PASS: sales form submitted and modal closed')
        else:
            print('FINDING: sales modal remained open after submission')
        await page.locator('[data-testid="nav-staff"]').click()
        await page.locator('[data-testid="add-staff-button"]').click()
        await page.fill('[data-testid="name-field"] input', 'TEST_UI Personel')
        await page.fill('[data-testid="shift-field"] input', '09:00')
        await page.fill('[data-testid="task-field"] input', 'TEST görev')
        await page.locator('[data-testid="save-entry-button"]').click()
        await page.wait_for_timeout(700)
        print('PASS: staff form submitted')
    except Exception as e:
        print(f'FINDING: UI test error: {e}')
        raise
    finally:
        error_text = await page.evaluate("""() => {
          const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
          return errorElements.map(el => el.textContent).join(', ');
        }""")
        print('FINDING: page error messages: ' + error_text if error_text else 'PASS: no page error messages')
