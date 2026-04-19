@echo off
echo Preparing to clean up and push updates to GitHub...

REM Explicitly remove .env from git tracking if it was accidentally pushed before
echo Untracking .env file...
git rm --cached .env

REM The -A flag adds all new files, tracks modifications, AND explicitly stages file deletions
echo Staging all changes...
git add -A

REM Commit the changes with a clean, descriptive message
git commit -m "Refactor backend, untrack .env natively, and prepare for Vercel deployment"

REM Push to the repository (Main branch)
echo Pushing to remote repository...
git push origin main

echo Push completed! Please check your repository.
pause
