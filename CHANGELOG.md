# Changelog

## [0.14.1](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.14.0...ai-sonar-bot-v0.14.1) (2026-04-09)


### Bug Fixes

* confidence for no findings ([98e48ba](https://github.com/JustinMelger/ai-sonar-bot/commit/98e48bafea35a600ee5ab47f2d02b6bba46d7ef5))
* prompt for lower confidence reviews ([e460c96](https://github.com/JustinMelger/ai-sonar-bot/commit/e460c961ab0c48610619d33fb7f93dea98deb215))
* prompt for lower confidence reviews ([5257124](https://github.com/JustinMelger/ai-sonar-bot/commit/52571245723ea2947691ffe67c64bf71af4c66e0))

## [0.14.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.13.0...ai-sonar-bot-v0.14.0) (2026-04-09)


### Features

* add context remedy issue in context bot ([d572a3e](https://github.com/JustinMelger/ai-sonar-bot/commit/d572a3e27ff7e21931150ada6ef3d8c77be89cac))
* improve review bot prompts and feedback ([7d0f21d](https://github.com/JustinMelger/ai-sonar-bot/commit/7d0f21de77792d3dd407464cec7d33c8488920a3))
* repo controls, agent guidance, ranking limit ([82de629](https://github.com/JustinMelger/ai-sonar-bot/commit/82de629e85982fa2a670ff9a6e1493a135b4eaf4))


### Documentation

* rename to docs ([e68bcc6](https://github.com/JustinMelger/ai-sonar-bot/commit/e68bcc6a1bbb9d971fd994c0a6c0e7c7e4184338))
* update roadmap and add hardening phase ([b66cae7](https://github.com/JustinMelger/ai-sonar-bot/commit/b66cae79b1e11c22d2268503f2cfce48ebcbd995))

## [0.13.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.12.1...ai-sonar-bot-v0.13.0) (2026-04-08)


### Features

* **dashboard:** add reconciliation workflow ([cb3430a](https://github.com/JustinMelger/ai-sonar-bot/commit/cb3430a6d0ab22a1bf2308953a46de6c767b413d))


### Documentation

* **reconciliation:** document dashboard reconcile workflow ([4c27229](https://github.com/JustinMelger/ai-sonar-bot/commit/4c27229bc9cdb096a46d17461588291cf282c0ab))
* **roadmap:** refocus roadmap on cleanup and review improvements ([e82e1b2](https://github.com/JustinMelger/ai-sonar-bot/commit/e82e1b2e39dd165c22e5d4eaa1e1f16ee75138b4))

## [0.12.1](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.12.0...ai-sonar-bot-v0.12.1) (2026-04-08)


### Bug Fixes

* mark manual on dashboard as rejected ([cb7db3c](https://github.com/JustinMelger/ai-sonar-bot/commit/cb7db3cf753d6c38d90f9e1ab82cd3ef9bdd1118))


### Documentation

* design and runbook ([5556e44](https://github.com/JustinMelger/ai-sonar-bot/commit/5556e44c47051279fb9bc6ce9833fa801304724f))

## [0.12.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.11.2...ai-sonar-bot-v0.12.0) (2026-04-08)


### Features

* add foundation remediation model ([676daf3](https://github.com/JustinMelger/ai-sonar-bot/commit/676daf3eccf4934d27e58194440e7610f308ebf6))
* add hard failure stage in runner ([2b6fbc1](https://github.com/JustinMelger/ai-sonar-bot/commit/2b6fbc106bfc81c4911e0b1f21e3adea53b071f1))
* dashboard normalisation for remediation ([90cb173](https://github.com/JustinMelger/ai-sonar-bot/commit/90cb173fde947dc09d66134bab2c366c54e65dc5))
* dedicated lifecylce updated ([ddbb3fc](https://github.com/JustinMelger/ai-sonar-bot/commit/ddbb3fc7f1c7e6f29cd9f5bb1ad4baca1f20324b))
* idempotent lifecycle writes for reruns ([e899468](https://github.com/JustinMelger/ai-sonar-bot/commit/e8994683393212e807032df6b10bcacf7ef211a9))
* tracebility dashboard state explicit ([be7514d](https://github.com/JustinMelger/ai-sonar-bot/commit/be7514ddb18bc3b737dc5d8f91c154a8d0a389ec))
* use stable dashboard items, add stale rule ([8dd14c1](https://github.com/JustinMelger/ai-sonar-bot/commit/8dd14c1379a58e4052df7518c38f26e10a313cc5))


### Bug Fixes

* dashboard sync only removes open not in sq ([94ad173](https://github.com/JustinMelger/ai-sonar-bot/commit/94ad1732f49bd776c12044b7a04e441086543e43))


### Documentation

* design remedy_bot ([70f0918](https://github.com/JustinMelger/ai-sonar-bot/commit/70f09187bff88f1d8f637e14ea921127af8ac322))
* update tech + functional docs dashboard remediation ([dcf19d4](https://github.com/JustinMelger/ai-sonar-bot/commit/dcf19d4a8c8abc0c95d26e189c7face795448eb4))
* updatedocs for new implementation ([a56a8c3](https://github.com/JustinMelger/ai-sonar-bot/commit/a56a8c3ef4c8566ac59afd527a2da000c2a8153a))

## [0.11.2](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.11.1...ai-sonar-bot-v0.11.2) (2026-04-06)


### Bug Fixes

* package version ([284dc50](https://github.com/JustinMelger/ai-sonar-bot/commit/284dc5080e425fcca37fe81c698d18874dee29ce))
* src lint import ([7a7f181](https://github.com/JustinMelger/ai-sonar-bot/commit/7a7f1819dcf0e8b12b02523c8274d52c867a7b94))
* type issue ([c38546b](https://github.com/JustinMelger/ai-sonar-bot/commit/c38546b752933fa4c0ca967db8a900692acc9e2e))


### Documentation

* update agent md ([27e8c0a](https://github.com/JustinMelger/ai-sonar-bot/commit/27e8c0a6e5b6790a333606ea4bf6528bc097df6e))

## [0.11.1](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.11.0...ai-sonar-bot-v0.11.1) (2026-04-06)


### Bug Fixes

* add completed items under correct header ([b681a33](https://github.com/JustinMelger/ai-sonar-bot/commit/b681a330611eeaf3f51a32acbef0fd3b1823116b))


### Documentation

* design dashboard based remedation bot ([9ef8a86](https://github.com/JustinMelger/ai-sonar-bot/commit/9ef8a8683920896026488c5542d09b57c9eacca4))
* design dashboard based remedation bot ([da0299c](https://github.com/JustinMelger/ai-sonar-bot/commit/da0299c6a44a93735bc6eedc643643fbe9c296b2))

## [0.11.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.10.0...ai-sonar-bot-v0.11.0) (2026-04-06)


### Features

* improve logging reviews ([5e286da](https://github.com/JustinMelger/ai-sonar-bot/commit/5e286da191a417e20775d6268e37817507a0f77c))


### Bug Fixes

* rm stale entries from dashboard when no longer in sq ([eaabea0](https://github.com/JustinMelger/ai-sonar-bot/commit/eaabea009b5579ea82941ba151f6d0fe6bed1334))


### Documentation

* add format ([e869a1a](https://github.com/JustinMelger/ai-sonar-bot/commit/e869a1a811bdaa1853e2a4bd544c6f01cbe133f0))

## [0.10.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.9.0...ai-sonar-bot-v0.10.0) (2026-04-05)


### Features

* collapse details ([0a538d3](https://github.com/JustinMelger/ai-sonar-bot/commit/0a538d384d733a927799738921a617bede588953))
* collapse details ([dba3165](https://github.com/JustinMelger/ai-sonar-bot/commit/dba316570f61ec5644b85047e52a4615c042a2ec))

## [0.9.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.8.0...ai-sonar-bot-v0.9.0) (2026-04-05)


### Features

* dashboard ui ([62e63fe](https://github.com/JustinMelger/ai-sonar-bot/commit/62e63fe0ef3c9b5f54b8f16a2b8cde775f84446f))
* dashboard ui ([8717f9d](https://github.com/JustinMelger/ai-sonar-bot/commit/8717f9db5150436544bff441a02ba4c10b2a3eed))


### Bug Fixes

* package not updatedafter release ([4ff3d04](https://github.com/JustinMelger/ai-sonar-bot/commit/4ff3d04cab50da2492daf0e4b6993a7eba96ef64))
* package not updatedafter release ([6faf93d](https://github.com/JustinMelger/ai-sonar-bot/commit/6faf93de349fde647dc237249ab658a87cdf65d5))

## [0.8.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.7.0...ai-sonar-bot-v0.8.0) (2026-04-05)


### Features

* add mirror for sq to dashboard ([c63cf03](https://github.com/JustinMelger/ai-sonar-bot/commit/c63cf0395b38efe1e6db5e43ce6686e3ca6ed2fd))

## [0.7.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.6.3...ai-sonar-bot-v0.7.0) (2026-04-05)


### Features

* add mirror for review to dashboard ([7e06303](https://github.com/JustinMelger/ai-sonar-bot/commit/7e06303d98af1d90b77448080e54bfc5633741d1))

## [0.6.3](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.6.2...ai-sonar-bot-v0.6.3) (2026-04-05)


### Bug Fixes

* run review only on triggered mr ([ad0813d](https://github.com/JustinMelger/ai-sonar-bot/commit/ad0813dacf4535a4139c728a9b2588a1ff4ef8c2))
* run review only on triggered mr ([4edd23f](https://github.com/JustinMelger/ai-sonar-bot/commit/4edd23f84d8e95cc39ca1e88a7aa25578fb7f8af))

## [0.6.2](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.6.1...ai-sonar-bot-v0.6.2) (2026-04-05)


### Bug Fixes

* optional weburl ([d39263d](https://github.com/JustinMelger/ai-sonar-bot/commit/d39263dc6c047f39576c957e0e978630a104a90d))
* optional weburl ([2b15b9b](https://github.com/JustinMelger/ai-sonar-bot/commit/2b15b9b9e545604655d50de2e55d4f2b7a90e9ac))

## [0.6.1](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.6.0...ai-sonar-bot-v0.6.1) (2026-04-05)


### Documentation

* update docs and new roadmap ([a1ed061](https://github.com/JustinMelger/ai-sonar-bot/commit/a1ed061061bbf8190c61d8a4d7e833b653463912))
* update docs and new roadmap ([aca309f](https://github.com/JustinMelger/ai-sonar-bot/commit/aca309f9127c7fd14603dc9251679ea62671af4d))

## [0.6.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.5.1...ai-sonar-bot-v0.6.0) (2026-04-05)


### Features

* gitlab review bot ([f11b383](https://github.com/JustinMelger/ai-sonar-bot/commit/f11b3834479bd869d714d7e34a04eeadc465a331))

## [0.5.1](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.5.0...ai-sonar-bot-v0.5.1) (2026-04-05)


### Documentation

* functional + techncial design review bot ([d3ddfa1](https://github.com/JustinMelger/ai-sonar-bot/commit/d3ddfa14d40ccc43c5b02d0eef36bd54208642d0))
* functional + techncial design review bot ([53abf7e](https://github.com/JustinMelger/ai-sonar-bot/commit/53abf7e54fafb04826f442d7580d455ebad4c93f))
* update roadmap for v1 review ([e34d31e](https://github.com/JustinMelger/ai-sonar-bot/commit/e34d31e33d53a5694f141e3aa1c16abaa9f8066e))

## [0.5.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.4.1...ai-sonar-bot-v0.5.0) (2026-04-04)


### Features

* feat:  ([824d9af](https://github.com/JustinMelger/ai-sonar-bot/commit/824d9aff24e324abd6fbbf559e0e5491c27e5dad))
* add rollback on failure ([c450824](https://github.com/JustinMelger/ai-sonar-bot/commit/c4508242abc09bdc92c56fff3d99cee3251a797e))
* improve logging and summaries ([299df3a](https://github.com/JustinMelger/ai-sonar-bot/commit/299df3af92753516dce97cf1023c68d53fb01905))
* persist structured edit artifacts ([164bc83](https://github.com/JustinMelger/ai-sonar-bot/commit/164bc831756d92d675f75c4e2cb127dd1ea19733))


### Bug Fixes

* **docs:** redirect link ([6b81c38](https://github.com/JustinMelger/ai-sonar-bot/commit/6b81c386b19bfe2c3055293842a1bc4cd64c17f3))
* **docs:** redirect link ([d1da99e](https://github.com/JustinMelger/ai-sonar-bot/commit/d1da99e1437a4696f88ff38b10bf8c70fed4ad7c))

## [0.4.1](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.4.0...ai-sonar-bot-v0.4.1) (2026-04-04)


### Bug Fixes

* exclude rename issues from v1 ([caf9f04](https://github.com/JustinMelger/ai-sonar-bot/commit/caf9f041724a10440d1c2acb25f25b072cef03de))
* exclude rename issues from v1 ([2084317](https://github.com/JustinMelger/ai-sonar-bot/commit/20843173b3f33b28db758d38dcef245a5b9c31b1))

## [0.4.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.3.1...ai-sonar-bot-v0.4.0) (2026-04-04)


### Features

* add template for mr ([4cb4cd8](https://github.com/JustinMelger/ai-sonar-bot/commit/4cb4cd884236259a3f00d363c1fd1639908220a7))
* add tests for issue selection ([b59b532](https://github.com/JustinMelger/ai-sonar-bot/commit/b59b532fea974d5e74a7f3dacba379727e861091))
* proceed with nex issue if mr already exists ([6e57ab9](https://github.com/JustinMelger/ai-sonar-bot/commit/6e57ab9efcb198680557d0c42bfcc3e49e7e4319))


### Documentation

* update roadmap for hardening phase ([86d66dd](https://github.com/JustinMelger/ai-sonar-bot/commit/86d66dd1e0d6eaa8f4c24c6f249e965b4d5d39af))
* v1 harderning roadmap ([df9aaad](https://github.com/JustinMelger/ai-sonar-bot/commit/df9aaad8882c3b2b998c9c2dfbc8c9fc361ed2f8))

## [0.3.1](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.3.0...ai-sonar-bot-v0.3.1) (2026-04-03)


### Bug Fixes

* release please versioning package ([528a53c](https://github.com/JustinMelger/ai-sonar-bot/commit/528a53ce7cf959b2e28829c5d92d4cfced28ff8c))

## [0.3.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.2.0...ai-sonar-bot-v0.3.0) (2026-04-03)


### Features

* add render models + edit ([a56c934](https://github.com/JustinMelger/ai-sonar-bot/commit/a56c934e3b2130c83bcfccf1cbecca68b8c57897))
* add strucutred edits for open ai client ([a9d3ddd](https://github.com/JustinMelger/ai-sonar-bot/commit/a9d3ddd72d3c8295e70152f961585a59fe929c58))


### Bug Fixes

* run lint on file ([7033216](https://github.com/JustinMelger/ai-sonar-bot/commit/7033216e9e98750d0cf3a413906f6bd13bd287e0))


### Documentation

* update rm for v1 ([6beebdc](https://github.com/JustinMelger/ai-sonar-bot/commit/6beebdcf4ca00a1d40afc4158c04bf861306cec8))
* update technical docs ([fe557b4](https://github.com/JustinMelger/ai-sonar-bot/commit/fe557b49fa8320bd8ad9a38372f47a270b056d3e))

## [0.2.0](https://github.com/JustinMelger/ai-sonar-bot/compare/ai-sonar-bot-v0.1.0...ai-sonar-bot-v0.2.0) (2026-03-29)


### Features

* add basic git ([380e957](https://github.com/JustinMelger/ai-sonar-bot/commit/380e9570eda554be9228a2b295dae4629e3a9d0e))
* add gitlab implementation ([d64828d](https://github.com/JustinMelger/ai-sonar-bot/commit/d64828d9c7029fd698d0e65a50c5fcf1014f98a4))
* add local approval ([7012e06](https://github.com/JustinMelger/ai-sonar-bot/commit/7012e069ae049289d5e35004f88ea03f3a20ca86))
* add OpenAI dry-run ([77dc7db](https://github.com/JustinMelger/ai-sonar-bot/commit/77dc7db5be342c6a076f5d70b3ddd223cb2b99b5))
* add patch application support for dry run ([4234ed0](https://github.com/JustinMelger/ai-sonar-bot/commit/4234ed05c9f5ac72411b0cf0a45cb6c88c11b659))
* add selected-issue context building and dry-run LLM analysis ([4952367](https://github.com/JustinMelger/ai-sonar-bot/commit/49523670e521ecbfb984c9ec702d3903fffce06f))
* add sq client ([582826c](https://github.com/JustinMelger/ai-sonar-bot/commit/582826c6c6440bf769e255f6e9bb36e2ecbfcd9d))
* **cicd:** add docker + release please ([283c40d](https://github.com/JustinMelger/ai-sonar-bot/commit/283c40de3e3a55322933440769f421b90a7cea1b))
* complete phase 3 +4, add dry run dummy issue for local dev ([c4464f8](https://github.com/JustinMelger/ai-sonar-bot/commit/c4464f854283f1eca695c6c7a553077faa7a09d9))
* improve failure logging ([01aafc6](https://github.com/JustinMelger/ai-sonar-bot/commit/01aafc6bcaf86dc38063907390413527e62abba0))
* low maintainiability sq issue selection ([8507396](https://github.com/JustinMelger/ai-sonar-bot/commit/85073965d32f344b0831a0c84e2010107971557a))
* scaffold project ([60428da](https://github.com/JustinMelger/ai-sonar-bot/commit/60428dae4d988c93b69e250c76ee4b7791d83cad))
* scaffold project ([7f61866](https://github.com/JustinMelger/ai-sonar-bot/commit/7f61866cf5289b31ebaeda33dfaae79faf9771bc))


### Bug Fixes

* run lint ([eea2d04](https://github.com/JustinMelger/ai-sonar-bot/commit/eea2d04390409b34f97e0f0dce95f87b0485bb14))
* run lint ([b6d52e1](https://github.com/JustinMelger/ai-sonar-bot/commit/b6d52e18871e62ad4898b15362a24d6ec72b4b00))
* run lint ([6de682d](https://github.com/JustinMelger/ai-sonar-bot/commit/6de682ddcbe289e38bef70b25e48f024a5f5deea))


### Documentation

* add engineering standards + update implementation docs ([14ac47b](https://github.com/JustinMelger/ai-sonar-bot/commit/14ac47b499654796bffc44366d868767b1f349be))
* add roadmap to v1 ([57b30cc](https://github.com/JustinMelger/ai-sonar-bot/commit/57b30cc3ecb9fa2750fa8b2bd6e18fa87b4b55c9))
* design ai sonar bot ([89a2396](https://github.com/JustinMelger/ai-sonar-bot/commit/89a23969e0b9913a6dcc4838cae165b4b89081db))
* update design for ci runner ([ea0d592](https://github.com/JustinMelger/ai-sonar-bot/commit/ea0d592c14c6e6eff4f66b4786f7b3fee0b32acc))
* update roadmap + design ([5d58b94](https://github.com/JustinMelger/ai-sonar-bot/commit/5d58b94520d2cf08584137dc02f7784129ba76c0))
