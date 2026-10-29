//! Help ▸ Check for updates opens O2CSI's releases in the browser. Unsigned portable builds
//! update manually; starting PdfCraft never checks, downloads or installs a release.

use crate::PdfCraftApp;

/// The same repository shown by Help ▸ O2CSI source on GitHub.
pub fn releases_page() -> String {
    format!("{}/releases", pdfcraft_engine::links::GITHUB)
}

impl PdfCraftApp {
    /// Open O2CSI's releases without changing the current documents or closing PdfCraft.
    pub fn check_for_updates(&mut self) {
        self.open_url(&releases_page());
    }
}
