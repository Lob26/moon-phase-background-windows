<#  MoonlightSonata.ps1
    Ejecuta la instalación del entorno, instala dependencias,
    crea (o recrea) la tarea “MoonlightSonata” y la lanza una vez. #>

# --------- Decoración -------------------------------------------------
$ascii = @'
 ****     ****   *******     *******   ****     **       ******     ******** 
/**/**   **/**  **/////**   **/////** /**/**   /**      /*////**   **//////**
/**//** ** /** **     //** **     //**/**//**  /**      /*   /**  **      // 
/** //***  /**/**      /**/**      /**/** //** /**      /******  /**         
/**  //*   /**/**      /**/**      /**/**  //**/**      /*//// **/**    *****
/**   /    /**//**     ** //**     ** /**   //****      /*    /**//**  ////**
/**        /** //*******   //*******  /**    //***      /*******  //******** 
//         //   ///////     ///////   //      ///       ///////    ////////  
'@
Write-Host $ascii -ForegroundColor Cyan
Write-Host "By: Pedro Lobato" -ForegroundColor DarkYellow
Write-Host

# --------- Variables de ruta -----------------------------------------
$here   = "$PSScriptRoot\"         # carpeta donde vive este .ps1, con barra final
$there  = $here.TrimEnd('\')       # sin barra final
$venv   = Join-Path $here 'pyscript'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$venvPip = Join-Path $venv 'Scripts\pip.exe'

# --------- Virtual env y dependencias ---------------------------------
if (-not (Test-Path $venv)) {
    & python -m venv $venv
    & $venvPy -m pip install --upgrade pip --quiet
    Write-Host "Virtual environment created and pip upgraded" -ForegroundColor Green
} else {
    Write-Host "Virtual environment already exists" -ForegroundColor Yellow
}

& $venvPip install -r "$here\requirements.txt" --quiet
Write-Host "Dependencies installed" -ForegroundColor Green

# --------- Generar XML temporal con rutas absolutas ------------------
$python  = Join-Path $venv 'Scripts\pythonw.exe'
$script  = Join-Path $here 'moonback.py'
$template = Get-Content "$here\wtask.template.xml"
$xmlTemp  = [IO.Path]::Combine($env:TEMP,'MoonlightSonata.xml')

$template `
  -replace '@@PYTHON@@',  $python `
  -replace '@@SCRIPT@@',  $script `
  -replace '@@WORKDIR@@', $there `
| Set-Content -Encoding Unicode -Path $xmlTemp

# --------- Borrar y recrear la tarea ---------------------------------
schtasks /delete /tn MoonlightSonata /f
Write-Host "Previous task (if any) deleted"

schtasks /create /tn "MoonlightSonata" /xml "$xmlTemp" /f
Write-Host "Task created from XML" -ForegroundColor Green

#Remove-Item $xmlTemp
Write-Host "Temporary XML removed"

# --------- Ejecutar la tarea una vez ---------------------------------
schtasks /run /tn MoonlightSonata
Write-Host "Task launched manually"

Write-Host "Setup complete - thanks!" -ForegroundColor Cyan
