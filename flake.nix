{
  description = "CloakBrowser development shell with Nix-packaged Chromium binaries";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;

      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forAllSystems = lib.genAttrs supportedSystems;

      chromiumVersion = "146.0.7680.177.3";

      packageInfo = {
        x86_64-linux = {
          platformTag = "linux-x64";
          hash = "sha256-WvAn+q+x/vmTPreEwJS3ZHBt4io3KizuhLwRf8SrU38=";
        };
        aarch64-linux = {
          platformTag = "linux-arm64";
          hash = "sha256-i3HOU7T9ExMnMxox+6ODXXGILRm/qr3njdD1OQvRb0U=";
        };
      };

      mkPkgs = system: import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };

      runtimeLibraries = pkgs: with pkgs; [
        alsa-lib
        at-spi2-atk
        at-spi2-core
        atk
        cairo
        cups
        dbus
        expat
        fontconfig
        freetype
        gdk-pixbuf
        glib
        gtk3
        libdrm
        libgbm
        libGL
        libpulseaudio
        libxkbcommon
        mesa
        nspr
        nss
        pango
        systemd
        wayland
        libx11
        libxcb
        libxcomposite
        libxcursor
        libxdamage
        libxext
        libxfixes
        libxi
        libxrandr
        libxrender
        libxscrnsaver
        libxshmfence
        libxtst
      ];

      fontPackages = pkgs: with pkgs; [
        freefont_ttf
        ipafont
        liberation_ttf
        noto-fonts
        noto-fonts-cjk-sans
        noto-fonts-color-emoji
        tlwg
        unifont
        wqy_zenhei
      ];

      mkCloakBrowserChromium = pkgs: system:
        let
          info = packageInfo.${system} or (throw "CloakBrowser flake package currently supports only x86_64-linux and aarch64-linux.");
          archiveName = "cloakbrowser-${info.platformTag}.tar.gz";
          libs = runtimeLibraries pkgs;
        in
        pkgs.stdenvNoCC.mkDerivation {
          pname = "cloakbrowser-chromium";
          version = chromiumVersion;

          src = pkgs.fetchurl {
            url = "https://cloakbrowser.dev/chromium-v${chromiumVersion}/${archiveName}";
            inherit (info) hash;
          };

          dontUnpack = true;

          nativeBuildInputs = with pkgs; [
            autoPatchelfHook
            makeWrapper
          ];

          buildInputs = libs;
          runtimeDependencies = libs;

          installPhase = ''
            runHook preInstall

            mkdir -p "$out/lib/cloakbrowser" "$out/bin"
            tar -xzf "$src" -C "$out/lib/cloakbrowser"
            chmod +x "$out/lib/cloakbrowser/chrome"

            runHook postInstall
          '';

          postFixup = ''
            makeWrapper "$out/lib/cloakbrowser/chrome" "$out/bin/cloakbrowser-chrome" \
              --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath libs}"
          '';

          meta = {
            description = "Official CloakBrowser patched Chromium binary";
            homepage = "https://github.com/CloakHQ/CloakBrowser";
            license = lib.licenses.unfreeRedistributable;
            mainProgram = "cloakbrowser-chrome";
            platforms = supportedSystems;
            sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
          };
        };
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = mkPkgs system;
          cloakbrowserChromium = mkCloakBrowserChromium pkgs system;
        in
        {
          inherit cloakbrowserChromium;
          default = cloakbrowserChromium;
        });

      devShells = forAllSystems (system:
        let
          pkgs = mkPkgs system;
          cloakbrowserChromium = self.packages.${system}.cloakbrowserChromium;
          python = pkgs.python312.withPackages (ps: with ps; [
            aiohttp
            geoip2
            hatchling
            httpx
            playwright
            pytest_8_3
            pytest-asyncio_0
            socksio
            websockets
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              cloakbrowserChromium
              python
              pkgs.cacert
              pkgs.curl
              pkgs.git
              pkgs.jq
              pkgs.nodejs_20
              pkgs.which
              pkgs.xdotool
              pkgs.xvfb-run
            ]
            ++ runtimeLibraries pkgs
            ++ fontPackages pkgs;

            shellHook = ''
              export CLOAKBROWSER_BINARY_PATH="${cloakbrowserChromium}/bin/cloakbrowser-chrome"
            '';
          };
        });
    };
}
