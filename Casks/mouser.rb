cask "mouser" do
  arch arm: "", intel: "-intel"

  version "3.6.0"
  sha256 :no_check

  url "https://github.com/TomBadash/Mouser/releases/download/v#{version}/Mouser-macOS#{arch}.zip",
      verified: "github.com/TomBadash/Mouser/"
  name "Mouser"
  desc "Open-source Logitech mouse remapper"
  homepage "https://github.com/TomBadash/Mouser"

  auto_updates true
  depends_on macos: :monterey

  app "Mouser.app"

  zap trash: [
    "~/Library/Application Support/Mouser",
    "~/Library/Caches/io.github.tombadash.mouser",
    "~/Library/HTTPStorages/io.github.tombadash.mouser",
    "~/Library/Preferences/io.github.tombadash.mouser.plist",
    "~/Library/Saved Application State/io.github.tombadash.mouser.savedState",
  ]

  caveats <<~EOS
    Mouser needs Accessibility permission to intercept mouse events.
    Open System Settings → Privacy & Security → Accessibility and enable Mouser.app.

    Logitech Options+ must not be running while Mouser is active.
  EOS
end
