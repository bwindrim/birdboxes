"""
Launcher for battmon implementation.
Delegates hardware-specific behavior to `battmon_impl` and core logic to `body`.
"""
import body
import battmon_impl as impl

if __name__ == '__main__':
    body.main(impl)
