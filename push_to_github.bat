@echo off
echo Preparing to clean up and push updates to GitHub...

REM The -A flag adds all new files, tracks modifications, AND explicitly stages file deletions (e.g. old code/ folders)
git add -A

REM Commit the changes with a clean, descriptive message
git commit -m "Refactor backend: Add Supabase Postgres integration, flatten project structure, and prepare for Vercel deployment"

REM Push to the repository (Main branch)
git push origin main

echo Push completed! Please check your repository.
pause
