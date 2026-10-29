//! O2CSI portable builds open their own releases only after Help ▸ Check for updates.

use egui_kittest::Harness;
use pdfcraft_ui_egui::PdfCraftApp;

const RELEASES: &str = "https://github.com/o2csi/pdfcraft/releases";

fn harness(setup: impl FnOnce(&mut PdfCraftApp) + 'static) -> Harness<'static, PdfCraftApp> {
    let mut h = Harness::builder().with_size(egui::vec2(1200.0, 800.0)).build_eframe(move |_cc| {
        let mut app = PdfCraftApp::new();
        app.set_option("language", "en").unwrap();
        setup(&mut app);
        app
    });
    h.run_steps(4);
    h
}

#[test]
fn check_for_updates_opens_the_o2csi_release_page() {
    let mut h = harness(|_| {});
    assert!(h.state_mut().execute("help.check_updates"));
    h.run_steps(2);
    assert_eq!(h.state().last_opened_url.as_deref(), Some(RELEASES));
}

#[test]
fn startup_does_not_open_releases_even_with_an_old_startup_preference() {
    let h = harness(|app| app.restore(r#"{"check_updates_at_start":true,"language":"en"}"#));
    assert_eq!(h.state().last_opened_url, None);
    assert_eq!(h.state().dialog, None);
}

#[test]
fn opening_releases_keeps_the_modified_document_open() {
    let pdf = b"%PDF-1.7\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF";
    let mut h = harness(move |app| {
        app.open_bytes("one.pdf", None, pdf.to_vec()).unwrap();
    });
    assert!(h.state_mut().execute("page.rotate"));
    h.run_steps(2);
    assert_eq!(h.state().first_dirty(), Some(0));
    let id = h.state().views[0].id;
    assert!(h.state_mut().execute("help.check_updates"));
    h.run_steps(3);
    let app = h.state();
    assert_eq!(app.last_opened_url.as_deref(), Some(RELEASES));
    assert_eq!(app.views.len(), 1);
    assert_eq!(app.views[0].id, id);
    let doc = app.session.get(id).unwrap();
    assert!(doc.dirty);
    assert_eq!(doc.info.pages[0].rotation, 90);
    assert_eq!(app.first_dirty(), Some(0));
    assert_eq!(app.dialog, None);
}
