# SignPath preflight, 2026-09-27

## Verified repository state

- Original application code is licensed Apache-2.0 in commit b7eb1ad.
- The desktop workflow builds Windows with PyInstaller and Inno Setup, then uploads and publishes unsigned artifacts. It also supports manual workflow dispatch.
- The PyInstaller spec includes all of assets and src/data. The latter contains two tracked starter Darwin Core ZIP archives. Their rights.txt files list CC BY-NC and CC BY records. Their original rights and citations must be retained; the app license does not cover them.
- The bundled guide screenshots include a photo example whose ownership and license have not been established by repository metadata.
- The Inno Setup version is 0.1.0 while pyproject.toml is 0.1.3.
- Local tags v0.1.1 through v0.1.3 exist. Public release assets were not verified because the GitHub page could not be fetched from this environment.

## Owner inputs needed before signing work

1. Decide whether the signed Windows installer should omit the CC BY-NC starter archives, or whether to prepare a replacement dataset with eligible rights. Keeping these archives in the signed package may fail SignPath's all-components license condition. Confirm whether their presence in the source repository is acceptable with SignPath during application.
2. Confirm ownership or redistribution permission for the guide images, especially assets/guides/quiz_page_walkthrough/current_photo.jpg. Replace or exclude any image that cannot be distributed under the selected terms.
3. Identify the GitHub account or team responsible for release signing approval. SignPath requires author, reviewer, and approver roles and MFA for team members.
4. Confirm a public Windows release download page for the application. SignPath requires a prior release in the form to be signed.

## Local preparation possible after those inputs

- Publish a code signing policy linked from the repository home page and release pages, with the required SignPath attribution, named roles, and an accurate privacy statement.
- Make Windows release metadata consistent with the tagged application version.
- Prepare a GitHub-hosted build artifact and fail-closed signing/publishing workflow. Verify signatures on the exact published files.

## Account steps after repository preparation

- The owner submits the SignPath Foundation application and waits for acceptance. Approval and timing are controlled by SignPath.
- After acceptance, the owner authorizes the SignPath GitHub App for this repository, establishes the SignPath project and signing policy, and stores a submitter API token directly in GitHub Actions secrets. Do not put the token in source control or chat.
- An authorized approver approves each release signing request.

## Sources

- SignPath Foundation terms: https://signpath.org/terms.html
- SignPath GitHub integration: https://docs.signpath.io/trusted-build-systems/github
- Inno Setup signed uninstaller: https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm
