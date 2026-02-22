# get-ui-tree.ps1
# Reads the Windows UI Automation accessibility tree for the foreground window
# Outputs a JSON object with window info and child elements

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

# Get the foreground window handle
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
}
"@

function Get-ElementInfo {
    param(
        [System.Windows.Automation.AutomationElement]$Element,
        [int]$Depth = 0,
        [int]$MaxDepth = 3
    )

    if ($null -eq $Element) { return $null }

    try {
        $current = $Element.Current
        $info = @{
            name        = $current.Name
            controlType = $current.ControlType.ProgrammaticName -replace 'ControlType\.', ''
            automationId = $current.AutomationId
            className   = $current.ClassName
            isEnabled   = $current.IsEnabled
            bounds      = @{
                x      = [int]$current.BoundingRectangle.X
                y      = [int]$current.BoundingRectangle.Y
                width  = [int]$current.BoundingRectangle.Width
                height = [int]$current.BoundingRectangle.Height
            }
        }

        # Try to get the Value pattern (for text fields, etc.)
        try {
            $valuePattern = $Element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
            if ($valuePattern) {
                $info.value = $valuePattern.Current.Value
            }
        } catch { }

        # Try to get toggle state (for checkboxes, etc.)
        try {
            $togglePattern = $Element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
            if ($togglePattern) {
                $info.toggleState = $togglePattern.Current.ToggleState.ToString()
            }
        } catch { }

        # Try to get selection state
        try {
            $selPattern = $Element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
            if ($selPattern) {
                $info.isSelected = $selPattern.Current.IsSelected
            }
        } catch { }

        # Recurse into children if not at max depth
        if ($Depth -lt $MaxDepth) {
            $children = @()
            $walker = [System.Windows.Automation.TreeWalker]::ContentViewWalker
            $child = $walker.GetFirstChild($Element)
            $childCount = 0
            $maxChildren = 50  # Limit to avoid huge trees

            while ($null -ne $child -and $childCount -lt $maxChildren) {
                $childInfo = Get-ElementInfo -Element $child -Depth ($Depth + 1) -MaxDepth $MaxDepth
                if ($null -ne $childInfo) {
                    $children += $childInfo
                }
                $child = $walker.GetNextSibling($child)
                $childCount++
            }

            if ($children.Count -gt 0) {
                $info.children = $children
            }

            if ($childCount -ge $maxChildren) {
                $info.truncated = $true
            }
        }

        return $info
    } catch {
        return @{ error = $_.Exception.Message }
    }
}

# Main execution
try {
    $hwnd = [Win32]::GetForegroundWindow()
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)

    if ($null -eq $root) {
        $output = @{ error = "Could not find foreground window" }
    } else {
        $current = $root.Current
        $output = @{
            window = @{
                title       = $current.Name
                processId   = $current.ProcessId
                className   = $current.ClassName
                bounds      = @{
                    x      = [int]$current.BoundingRectangle.X
                    y      = [int]$current.BoundingRectangle.Y
                    width  = [int]$current.BoundingRectangle.Width
                    height = [int]$current.BoundingRectangle.Height
                }
            }
            elements = @()
        }

        # Get children of the window
        $walker = [System.Windows.Automation.TreeWalker]::ContentViewWalker
        $child = $walker.GetFirstChild($root)
        $elements = @()
        $count = 0
        $maxTopLevel = 80

        while ($null -ne $child -and $count -lt $maxTopLevel) {
            $childInfo = Get-ElementInfo -Element $child -Depth 1 -MaxDepth 3
            if ($null -ne $childInfo) {
                $elements += $childInfo
            }
            $child = $walker.GetNextSibling($child)
            $count++
        }

        $output.elements = $elements
        $output.elementCount = $elements.Count
    }

    $output | ConvertTo-Json -Depth 10 -Compress
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Compress
}
