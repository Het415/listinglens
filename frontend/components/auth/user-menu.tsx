'use client'

import Link from 'next/link'
import { useRef, useState } from 'react'
import { FolderOpen, LogOut, Trash2 } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { deleteUser, signOut, useSession } from '@/lib/auth-client'
import { SignInDialog } from './sign-in-dialog'

function clearLocalHistories() {
  // The chat mirror in sessionStorage belongs to whoever was signed in; drop
  // it on sign-out so the next person at this browser doesn't see it.
  for (let i = sessionStorage.length - 1; i >= 0; i--) {
    const key = sessionStorage.key(i)
    if (key?.startsWith('assistant_history_')) sessionStorage.removeItem(key)
  }
}

export function UserMenu() {
  const { data: session, isPending } = useSession()
  const [signInOpen, setSignInOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // The placeholder is for the very first load only. useSession re-checks on
  // window focus, and swapping the menu out mid-check would unmount an open
  // sign-in dialog.
  const resolved = useRef(false)
  if (!isPending) resolved.current = true
  if (isPending && !resolved.current) {
    return <span className="size-9 shrink-0 rounded-full bg-border/60 animate-pulse" aria-hidden />
  }

  if (!session) {
    return (
      <>
        <button
          type="button"
          onClick={() => setSignInOpen(true)}
          className="inline-flex h-9 shrink-0 items-center rounded-lg border border-border bg-background-card px-3 text-sm text-text-secondary transition-colors hover:border-border-hover hover:text-text-primary"
        >
          Sign in
        </button>
        <SignInDialog open={signInOpen} onOpenChange={setSignInOpen} />
      </>
    )
  }

  const { user } = session
  const initial = (user.name || user.email || '?').trim().charAt(0).toUpperCase()

  const handleSignOut = async () => {
    await signOut()
    clearLocalHistories()
    window.location.reload()
  }

  const handleDelete = async () => {
    setDeleteError(null)
    const res = await deleteUser()
    if (res?.error) {
      // Better Auth asks for a recent sign-in before deleting an account.
      setDeleteError(res.error.message || 'Could not delete the account. Sign in again and retry.')
      return
    }
    clearLocalHistories()
    window.location.assign('/')
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="Account menu"
          className="inline-flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-background-card text-sm font-medium text-text-primary hover:border-border-hover"
        >
          {user.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={user.image} alt="" className="size-full object-cover" referrerPolicy="no-referrer" />
          ) : (
            initial
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel className="font-normal">
            <div className="truncate text-sm text-foreground">{user.name}</div>
            <div className="truncate text-xs text-muted-foreground">{user.email}</div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild>
            <Link href="/dashboard/reports">
              <FolderOpen className="size-4" /> My reports
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={handleSignOut}>
            <LogOut className="size-4" /> Sign out
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={() => setConfirmDelete(true)}>
            <Trash2 className="size-4" /> Delete account
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete your account?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes your account and every report and chat saved to it. It can&apos;t
              be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                void handleDelete()
              }}
            >
              Delete account
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
